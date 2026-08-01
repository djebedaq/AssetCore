from __future__ import annotations

from collections.abc import Callable
from enum import Enum

from fastapi import Depends, HTTPException, status

from .models import User, UserRole
from .security import get_current_active_user


class Permission(str, Enum):
    USERS_VIEW = "users.view"
    USERS_CREATE = "users.create"
    USERS_EDIT = "users.edit"
    USERS_ACTIVATE = "users.activate"
    USERS_DEACTIVATE = "users.deactivate"
    USERS_RESET_PASSWORD = "users.reset_password"
    USERS_ASSIGN_DIRECTOR = "users.assign_director"
    USERS_ASSIGN_ADMINISTRATOR = "users.assign_administrator"
    ASSETS_VIEW = "assets.view"
    ASSETS_CREATE = "assets.create"
    ASSETS_EDIT = "assets.edit"
    ASSETS_CHANGE_LOCATION = "assets.change_location"
    TRANSFERS_VIEW = "transfers.view"
    TRANSFERS_CREATE = "transfers.create"
    TRANSFERS_RETURN = "transfers.return"
    REPAIRS_VIEW = "repairs.view"
    REPAIRS_CREATE = "repairs.create"
    REPAIRS_EDIT = "repairs.edit"
    REPAIRS_COMPLETE = "repairs.complete"
    REQUESTS_VIEW = "requests.view"
    REQUESTS_CREATE = "requests.create"
    REQUESTS_APPROVE = "requests.approve"
    PARTS_VIEW = "parts.view"
    PARTS_MANAGE = "parts.manage"
    DOCUMENTS_VIEW = "documents.view"
    DOCUMENTS_GENERATE = "documents.generate"
    TEMPLATES_MANAGE = "templates.manage"
    AUDIT_VIEW_OPERATIONAL = "audit.view_operational"
    AUDIT_VIEW_FULL = "audit.view_full"
    SETTINGS_MANAGE = "settings.manage"


ALL_PERMISSIONS = frozenset(Permission)

ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    UserRole.ADMINISTRATOR.value: ALL_PERMISSIONS,
    UserRole.DIRECTOR.value: frozenset(
        {
            Permission.USERS_VIEW,
            Permission.USERS_CREATE,
            Permission.USERS_EDIT,
            Permission.USERS_ACTIVATE,
            Permission.USERS_DEACTIVATE,
            Permission.USERS_RESET_PASSWORD,
            Permission.ASSETS_VIEW,
            Permission.TRANSFERS_VIEW,
            Permission.TRANSFERS_CREATE,
            Permission.TRANSFERS_RETURN,
            Permission.REPAIRS_VIEW,
            Permission.REPAIRS_CREATE,
            Permission.REPAIRS_EDIT,
            Permission.REPAIRS_COMPLETE,
            Permission.REQUESTS_VIEW,
            Permission.REQUESTS_CREATE,
            Permission.REQUESTS_APPROVE,
            Permission.PARTS_VIEW,
            Permission.DOCUMENTS_VIEW,
            Permission.DOCUMENTS_GENERATE,
            Permission.AUDIT_VIEW_OPERATIONAL,
        }
    ),
    UserRole.MECHANIC.value: frozenset(
        {
            Permission.ASSETS_VIEW,
            Permission.TRANSFERS_VIEW,
            Permission.TRANSFERS_CREATE,
            Permission.TRANSFERS_RETURN,
            Permission.REPAIRS_VIEW,
            Permission.REPAIRS_CREATE,
            Permission.REPAIRS_EDIT,
            Permission.REPAIRS_COMPLETE,
            Permission.REQUESTS_VIEW,
            Permission.REQUESTS_CREATE,
            Permission.PARTS_VIEW,
            Permission.DOCUMENTS_VIEW,
            Permission.DOCUMENTS_GENERATE,
        }
    ),
    UserRole.OBSERVER.value: frozenset({Permission.ASSETS_VIEW}),
}


def permissions_for(user: User) -> list[str]:
    return sorted(permission.value for permission in ROLE_PERMISSIONS.get(user.role, ()))


def has_permission(user: User, permission: Permission | str) -> bool:
    try:
        required = permission if isinstance(permission, Permission) else Permission(permission)
    except ValueError:
        return False
    return required in ROLE_PERMISSIONS.get(user.role, ())


def is_observer(user: User) -> bool:
    return user.role == UserRole.OBSERVER.value


def ensure_permission(user: User, permission: Permission) -> None:
    if not has_permission(user, permission):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "permission_denied",
                "message": "Нямате права за това действие.",
                "permission": permission.value,
            },
        )


def require_permission(permission: Permission) -> Callable[..., User]:
    def dependency(user: User = Depends(get_current_active_user)) -> User:
        ensure_permission(user, permission)
        return user

    return dependency
