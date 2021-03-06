from datetime import datetime
from typing import Optional, List, Any, Union, Sequence

from fastapi_amis_admin.amis.components import InputImage, ColumnImage
from fastapi_amis_admin.models.fields import Field
from fastapi_amis_admin.utils.translation import i18n as _
from pydantic import EmailStr, SecretStr
from sqlalchemy import Column, String, and_
from sqlalchemy.orm import backref, Session
from sqlalchemy.sql.selectable import Exists
from sqlmodel import SQLModel, Relationship, select
from sqlmodel.sql.expression import SelectOfScalar

SelectOfScalar.inherit_cache = True


class SQLModelTable(SQLModel):
    id: int = Field(default=None, primary_key=True, nullable=False)


class UserRoleLink(SQLModel, table=True):
    __tablename__ = 'auth_user_roles'
    user_id: Optional[int] = Field(
        default=None, foreign_key="auth_user.id", primary_key=True, nullable=False
    )
    role_id: Optional[int] = Field(
        default=None, foreign_key="auth_role.id", primary_key=True, nullable=False
    )


class UserGroupLink(SQLModel, table=True):
    __tablename__ = 'auth_user_groups'
    user_id: Optional[int] = Field(
        default=None, foreign_key="auth_user.id", primary_key=True, nullable=False
    )
    group_id: Optional[int] = Field(
        default=None, foreign_key="auth_group.id", primary_key=True, nullable=False
    )


class GroupRoleLink(SQLModel, table=True):
    __tablename__ = 'auth_group_roles'
    group_id: Optional[int] = Field(
        default=None, foreign_key="auth_group.id", primary_key=True, nullable=False
    )
    role_id: Optional[int] = Field(
        default=None, foreign_key="auth_role.id", primary_key=True, nullable=False
    )


class RolePermissionLink(SQLModel, table=True):
    __tablename__ = 'auth_role_permissions'
    role_id: Optional[int] = Field(
        default=None, foreign_key="auth_role.id", primary_key=True, nullable=False
    )
    permission_id: Optional[int] = Field(
        default=None, foreign_key="auth_permission.id", primary_key=True, nullable=False
    )


class UserUsername(SQLModel):
    username: str = Field(
        title=_('Username'), max_length=32,
        sa_column=Column(String(32), unique=True, index=True, nullable=False)
    )


class PasswordStr(SecretStr, str):
    pass


class UserPassword(SQLModel):
    password: PasswordStr = Field(
        title=_('Password'), max_length=128,
        sa_column=Column(String(128), nullable=False),
        amis_form_item='input-password'
    )


class UserEmail(SQLModel):
    email: EmailStr = Field(
        title=_('Email'),
        sa_column=Column(String(50), unique=True, index=True, nullable=False),
        amis_form_item='input-email'
    )


class BaseUser(UserEmail, UserPassword, UserUsername, SQLModelTable):
    __tablename__ = 'auth_user'
    __table_args__ = {'extend_existing': True}
    is_active: bool = Field(default=True, title=_('Is Active'))
    nickname: str = Field(None, title=_('Nickname'), max_length=32)
    avatar: str = Field(None, title=_('Avatar'), max_length=100,
                        amis_form_item=InputImage(maxLength=1, maxSize=2 * 1024 * 1024,
                                                  receiver='post:/admin/file/upload'),
                        amis_table_column=ColumnImage(width=50, height=50, enlargeAble=True))
    create_time: datetime = Field(default_factory=datetime.utcnow, title=_('Create Time'))

    class Config:
        use_enum_values = True

    @property
    def is_authenticated(self) -> bool:
        return self.is_active

    @property
    def display_name(self) -> str:
        return self.nickname or self.username

    @property
    def identity(self) -> str:
        return self.username

    def _exists_role(self, *role_whereclause: Any) -> Exists:
        # check user role
        user_role_ids = select(Role.id).join(
            UserRoleLink, (UserRoleLink.user_id == self.id) & (UserRoleLink.role_id == Role.id)
        ).where(*role_whereclause)
        # check user group
        role_group_ids = select(GroupRoleLink.group_id).join(
            Role, and_(*role_whereclause, Role.id == GroupRoleLink.role_id))
        group_user_ids = select(UserGroupLink.user_id).where(UserGroupLink.user_id == self.id).where(
            UserGroupLink.group_id.in_(role_group_ids)
        )
        return user_role_ids.exists() | group_user_ids.exists()

    def _exists_roles(self, roles: List[str]) -> Exists:
        """
        ??????????????????????????????????????????,?????????????????????????????????????????????
        Args:
            roles:

        Returns:

        """
        return self._exists_role(Role.key.in_(roles))

    def _exists_groups(self, groups: List[str]) -> Exists:
        """
        ???????????????????????????????????????
        Args:
            groups:

        Returns:

        """
        group_ids = select(Group.id).join(
            UserGroupLink, (UserGroupLink.user_id == self.id) & (UserGroupLink.group_id == Group.id)
        ).where(Group.key.in_(groups))
        return group_ids.exists()

    def _exists_permissions(self, permissions: List[str]) -> Exists:
        """
        ?????????????????????????????????????????????????????????
        Args:
            permissions:

        Returns:

        """
        role_ids = select(RolePermissionLink.role_id).join(
            Permission, Permission.key.in_(permissions) & (Permission.id == RolePermissionLink.permission_id)
        )
        return self._exists_role(Role.id.in_(role_ids))

    def has_requires(
            self,
            session: Session,
            *,
            roles: Union[str, Sequence[str]] = None,
            groups: Union[str, Sequence[str]] = None,
            permissions: Union[str, Sequence[str]] = None,
    ) -> bool:
        """
        ???????????????????????????????????????RBAC??????
        Args:
            session: sqlalchemy `Session`;??????`AsyncSession`,?????????`run_sync`??????.
            roles: ????????????
            groups: ???????????????
            permissions: ????????????

        Returns:
            ??????????????????`True`
        """
        stmt = select(1)
        if groups:
            groups_list = [groups] if isinstance(groups, str) else list(groups)
            stmt = stmt.where(self._exists_groups(groups_list))
        if roles:
            roles_list = [roles] if isinstance(roles, str) else list(roles)
            stmt = stmt.where(self._exists_roles(roles_list))
        if permissions:
            permissions_list = [permissions] if isinstance(permissions, str) else list(permissions)
            stmt = stmt.where(self._exists_permissions(permissions_list))
        return bool(session.scalar(stmt))


class User(BaseUser, table=True):
    """??????"""
    point: float = Field(default=0, title=_('Point'))
    phone: str = Field(None, title=_('Tel'), max_length=15)
    parent_id: int = Field(None, title=_('Parent'), foreign_key="auth_user.id")
    children: List["User"] = Relationship(
        sa_relationship_kwargs=dict(
            backref=backref("parent", remote_side="User.id"),
        ),
    )
    roles: List["Role"] = Relationship(back_populates="users", link_model=UserRoleLink)
    groups: List["Group"] = Relationship(back_populates="users", link_model=UserGroupLink)


class BaseRBAC(SQLModelTable):
    __table_args__ = {'extend_existing': True}
    key: str = Field(..., title=_('Identify'), max_length=20,
                     sa_column=Column(String(20), unique=True, index=True, nullable=False))
    name: str = Field(..., title=_('Name'), max_length=20)
    desc: str = Field(default='', title=_('Description'), max_length=400, amis_form_item='textarea')


class Role(BaseRBAC, table=True):
    """??????"""
    __tablename__ = 'auth_role'
    users: List[User] = Relationship(back_populates="roles", link_model=UserRoleLink)
    groups: List["Group"] = Relationship(back_populates="roles", link_model=GroupRoleLink)
    permissions: List["Permission"] = Relationship(back_populates="roles", link_model=RolePermissionLink)


class Group(BaseRBAC, table=True):
    """?????????"""
    __tablename__ = 'auth_group'
    parent_id: int = Field(None, title=_('Parent'), foreign_key="auth_group.id")
    users: List[User] = Relationship(back_populates="groups", link_model=UserGroupLink)
    roles: List["Role"] = Relationship(back_populates="groups", link_model=GroupRoleLink)


class Permission(BaseRBAC, table=True):
    """??????"""
    __tablename__ = 'auth_permission'
    roles: List["Role"] = Relationship(back_populates="permissions", link_model=RolePermissionLink)
