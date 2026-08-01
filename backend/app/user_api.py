from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .audit import add_audit_log
from .database import get_db
from .licensing import active_license
from .models import Department, ProfileStatus, User, UserRole, utcnow
from .permissions import Permission, has_permission, permissions_for, require_permission
from .schemas import (
    ChangePasswordRequest,
    PasswordResetRequest,
    TokenResponse,
    UserActionResponse,
    UserCreate,
    UserOut,
    UserUpdate,
)
from .security import (
    create_access_token,
    get_authenticated_user,
    hash_password,
    validate_password_policy,
    verify_password,
)
from .settings import settings

router = APIRouter(prefix="/api", tags=["users"])


def serialize_user(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "first_name": user.first_name,
        "middle_name": user.middle_name,
        "last_name": user.last_name,
        "job_title": user.job_title,
        "department_id": user.department_id,
        "profile_status": user.profile_status,
        "legal_name_exception": user.legal_name_exception,
        "legal_name_exception_reason": user.legal_name_exception_reason,
        "legal_name_exception_approved_by_id": user.legal_name_exception_approved_by_id,
        "legal_name_exception_approved_at": user.legal_name_exception_approved_at,
        "role": user.role,
        "preferred_language": user.preferred_language,
        "is_active": user.is_active,
        "is_system_owner": user.is_system_owner,
        "must_change_password": user.must_change_password,
        "permissions": permissions_for(user),
        "created_at": user.created_at,
        "updated_at": user.updated_at or user.created_at,
        "last_login_at": user.last_login_at,
        "password_changed_at": user.password_changed_at,
        "created_by_id": user.created_by_id,
    }


def _correlation_id(request: Request) -> str | None:
    value = request.headers.get("X-Request-ID", "")
    return value if re.fullmatch(r"[A-Za-z0-9._:-]{1,80}", value) else None


def _reject(
    db: Session,
    actor: User,
    request: Request,
    target: User | None,
    action: str,
    code: str,
    message: str,
) -> None:
    add_audit_log(
        db,
        actor,
        "user_account",
        target.id if target else None,
        action,
        {
            "result": "rejected",
            "target_user_id": target.id if target else None,
            "old_role": target.role if target else None,
            "old_active": target.is_active if target else None,
            "reason": code,
        },
        _correlation_id(request),
    )
    db.commit()
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": code, "message": message},
    )


def _get_target(db: Session, user_id: int) -> User:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "user_not_found", "message": "Потребителят не е намерен."},
        )
    return target


def _can_manage(actor: User, target: User) -> bool:
    if target.is_system_owner:
        return False
    if actor.is_system_owner and actor.role == UserRole.ADMINISTRATOR.value:
        return target.role in {
            UserRole.DIRECTOR.value,
            UserRole.MECHANIC.value,
            UserRole.OBSERVER.value,
        }
    return actor.role == UserRole.DIRECTOR.value and target.role in {
        UserRole.MECHANIC.value,
        UserRole.OBSERVER.value,
    }


def _ensure_manageable(
    db: Session,
    actor: User,
    target: User,
    request: Request,
    action: str,
) -> None:
    if target.is_system_owner:
        _reject(
            db,
            actor,
            request,
            target,
            action,
            "system_owner_protected",
            "Основният администратор не може да бъде променян.",
        )
    if not _can_manage(actor, target):
        _reject(
            db,
            actor,
            request,
            target,
            action,
            "user_scope_denied",
            "Нямате права за управление на този потребител.",
        )


@router.get("/users", response_model=list[UserOut])
def list_users(
    search: str | None = Query(default=None, max_length=255),
    role: UserRole | None = None,
    is_active: bool | None = None,
    actor: User = Depends(require_permission(Permission.USERS_VIEW)),
    db: Session = Depends(get_db),
) -> list[dict]:
    query = select(User)
    if actor.role == UserRole.DIRECTOR.value:
        query = query.where(
            User.role.in_([UserRole.MECHANIC.value, UserRole.OBSERVER.value])
        )
    if search and search.strip():
        value = f"%{search.strip().casefold()}%"
        query = query.where(
            or_(func.lower(User.email).like(value), func.lower(User.full_name).like(value))
        )
    if role is not None:
        query = query.where(User.role == role.value)
    if is_active is not None:
        query = query.where(User.is_active.is_(is_active))
    return [serialize_user(user) for user in db.scalars(query.order_by(User.full_name, User.id))]


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    data: UserCreate,
    request: Request,
    actor: User = Depends(require_permission(Permission.USERS_CREATE)),
    db: Session = Depends(get_db),
) -> dict:
    allowed = {UserRole.MECHANIC, UserRole.OBSERVER}
    if actor.is_system_owner and has_permission(
        actor, Permission.USERS_ASSIGN_DIRECTOR
    ):
        allowed.add(UserRole.DIRECTOR)
    if data.role not in allowed:
        _reject(
            db,
            actor,
            request,
            None,
            "Отказан опит за повишаване на роля",
            "role_escalation_denied",
            "Нямате права да зададете избраната роля.",
        )
    licence = active_license(db) if settings.license_enforcement_enabled else None
    if licence is not None:
        max_users = int(licence.payload.get("max_users", 0))
        current_users = db.scalar(select(func.count(User.id))) or 0
        if max_users and current_users >= max_users:
            _reject(
                db,
                actor,
                request,
                None,
                "Отказано създаване на потребител поради лицензно ограничение",
                "license_user_limit_reached",
                "Достигнат е максималният брой потребители по активния лиценз.",
            )
    if db.scalar(select(User.id).where(func.lower(User.email) == data.email)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "duplicate_email",
                "message": "Вече съществува потребител с този имейл.",
            },
        )
    if data.department_id is not None and db.get(Department, data.department_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "department_not_found", "message": "Отделът не е намерен."},
        )
    user = User(
        email=data.email,
        full_name=" ".join([data.first_name, data.middle_name, data.last_name]),
        first_name=data.first_name,
        middle_name=data.middle_name,
        last_name=data.last_name,
        job_title=data.job_title,
        department_id=data.department_id,
        profile_status=ProfileStatus.COMPLETE.value,
        password_hash=hash_password(data.temporary_password),
        role=data.role.value,
        preferred_language=data.preferred_language.value,
        is_active=data.is_active,
        is_system_owner=False,
        must_change_password=True,
        created_by_id=actor.id,
    )
    db.add(user)
    try:
        db.flush()
        add_audit_log(
            db,
            actor,
            "user_account",
            user.id,
            "Създаден потребител",
            {
                "target_user_id": user.id,
                "new_role": user.role,
                "new_active": user.is_active,
                "preferred_language": user.preferred_language,
            },
            _correlation_id(request),
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "duplicate_email", "message": "Имейлът вече се използва."},
        ) from exc
    db.refresh(user)
    return serialize_user(user)


@router.get("/users/{user_id}", response_model=UserOut)
def get_user(
    user_id: int,
    actor: User = Depends(require_permission(Permission.USERS_VIEW)),
    db: Session = Depends(get_db),
) -> dict:
    target = _get_target(db, user_id)
    if actor.role == UserRole.DIRECTOR.value and target.role not in {
        UserRole.MECHANIC.value,
        UserRole.OBSERVER.value,
    }:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "user_scope_denied", "message": "Нямате достъп до този профил."},
        )
    return serialize_user(target)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    data: UserUpdate,
    request: Request,
    actor: User = Depends(require_permission(Permission.USERS_EDIT)),
    db: Session = Depends(get_db),
) -> dict:
    target = _get_target(db, user_id)
    _ensure_manageable(db, actor, target, request, "Отказана промяна на потребител")
    if actor.id == target.id and data.role is not None:
        _reject(
            db, actor, request, target, "Отказана промяна на собствена роля",
            "self_role_change_denied", "Не можете да промените собствената си роля."
        )
    if actor.id == target.id and data.is_active is False:
        _reject(
            db, actor, request, target, "Отказано самостоятелно деактивиране",
            "self_deactivation_denied", "Не можете да деактивирате собствения си акаунт."
        )
    if data.role is not None:
        allowed_roles = {UserRole.MECHANIC, UserRole.OBSERVER}
        if actor.is_system_owner and has_permission(
            actor, Permission.USERS_ASSIGN_DIRECTOR
        ):
            allowed_roles.add(UserRole.DIRECTOR)
        if data.role not in allowed_roles:
            _reject(
                db, actor, request, target, "Отказан опит за повишаване на роля",
                "role_escalation_denied", "Нямате права да зададете избраната роля."
            )
    old = {
        "role": target.role,
        "active": target.is_active,
        "full_name": target.full_name,
        "preferred_language": target.preferred_language,
    }
    changes = data.model_dump(exclude_unset=True, exclude_none=True)
    # The separated identity fields are authoritative. A legacy full_name-only
    # update must never overwrite a complete structured identity.
    changes.pop("full_name", None)
    if "department_id" in changes and db.get(Department, changes["department_id"]) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "department_not_found", "message": "Отделът не е намерен."},
        )
    if "role" in changes:
        changes["role"] = data.role.value
    if "preferred_language" in changes:
        changes["preferred_language"] = data.preferred_language.value
    for field, value in changes.items():
        setattr(target, field, value)
    identity_fields = {"first_name", "middle_name", "last_name", "job_title"}
    if identity_fields.intersection(changes):
        if target.first_name and target.last_name:
            target.full_name = " ".join(
                filter(None, [target.first_name, target.middle_name, target.last_name])
            )
        has_middle = bool(target.middle_name) or (
            target.legal_name_exception
            and bool(target.legal_name_exception_reason)
            and bool(target.legal_name_exception_approved_by_id)
            and bool(target.legal_name_exception_approved_at)
        )
        target.profile_status = (
            ProfileStatus.COMPLETE.value
            if target.first_name and has_middle and target.last_name and target.job_title
            else ProfileStatus.INCOMPLETE.value
        )
    if target.role != old["role"] or target.is_active != old["active"]:
        target.token_version += 1
    target.updated_at = utcnow()
    add_audit_log(
        db,
        actor,
        "user_account",
        target.id,
        "Променен потребител",
        {
            "target_user_id": target.id,
            "old_role": old["role"],
            "new_role": target.role,
            "old_active": old["active"],
            "new_active": target.is_active,
            "name_changed": old["full_name"] != target.full_name,
            "old_language": old["preferred_language"],
            "new_language": target.preferred_language,
        },
        _correlation_id(request),
    )
    db.commit()
    db.refresh(target)
    return serialize_user(target)


def _set_active(
    user_id: int,
    value: bool,
    request: Request,
    actor: User,
    db: Session,
) -> dict:
    target = _get_target(db, user_id)
    action = "Активиран потребител" if value else "Деактивиран потребител"
    _ensure_manageable(db, actor, target, request, action)
    if not value and actor.id == target.id:
        _reject(
            db, actor, request, target, "Отказано самостоятелно деактивиране",
            "self_deactivation_denied", "Не можете да деактивирате собствения си акаунт."
        )
    old_active = target.is_active
    target.is_active = value
    target.token_version += 1
    target.updated_at = utcnow()
    add_audit_log(
        db,
        actor,
        "user_account",
        target.id,
        action,
        {
            "target_user_id": target.id,
            "old_role": target.role,
            "new_role": target.role,
            "old_active": old_active,
            "new_active": target.is_active,
        },
        _correlation_id(request),
    )
    db.commit()
    db.refresh(target)
    return serialize_user(target)


@router.post("/users/{user_id}/activate", response_model=UserActionResponse)
def activate_user(
    user_id: int,
    request: Request,
    actor: User = Depends(require_permission(Permission.USERS_ACTIVATE)),
    db: Session = Depends(get_db),
) -> dict:
    return {"message": "Потребителят е активиран.", "user": _set_active(user_id, True, request, actor, db)}


@router.post("/users/{user_id}/deactivate", response_model=UserActionResponse)
def deactivate_user(
    user_id: int,
    request: Request,
    actor: User = Depends(require_permission(Permission.USERS_DEACTIVATE)),
    db: Session = Depends(get_db),
) -> dict:
    return {"message": "Потребителят е деактивиран.", "user": _set_active(user_id, False, request, actor, db)}


@router.post("/users/{user_id}/reset-password", response_model=UserActionResponse)
def reset_password(
    user_id: int,
    data: PasswordResetRequest,
    request: Request,
    actor: User = Depends(require_permission(Permission.USERS_RESET_PASSWORD)),
    db: Session = Depends(get_db),
) -> dict:
    target = _get_target(db, user_id)
    _ensure_manageable(db, actor, target, request, "Отказано нулиране на парола")
    try:
        validate_password_policy(data.temporary_password, target.email)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "password_policy", "message": str(exc)},
        ) from exc
    target.password_hash = hash_password(data.temporary_password)
    target.must_change_password = True
    target.password_changed_at = utcnow()
    target.updated_at = utcnow()
    target.token_version += 1
    add_audit_log(
        db,
        actor,
        "user_account",
        target.id,
        "Нулирана парола",
        {"target_user_id": target.id, "must_change_password": True},
        _correlation_id(request),
    )
    db.commit()
    db.refresh(target)
    return {"message": "Зададена е нова временна парола.", "user": serialize_user(target)}


@router.post("/auth/change-password", response_model=TokenResponse)
def change_password(
    data: ChangePasswordRequest,
    request: Request,
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
) -> TokenResponse:
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "current_password_invalid", "message": "Текущата парола е неправилна."},
        )
    if verify_password(data.new_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "password_reuse", "message": "Новата парола трябва да е различна."},
        )
    try:
        validate_password_policy(data.new_password, user.email)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "password_policy", "message": str(exc)},
        ) from exc
    user.password_hash = hash_password(data.new_password)
    user.password_changed_at = utcnow()
    user.updated_at = utcnow()
    user.must_change_password = False
    user.token_version += 1
    add_audit_log(
        db,
        user,
        "user_account",
        user.id,
        "Променена собствена парола",
        {"target_user_id": user.id, "must_change_password": False},
        _correlation_id(request),
    )
    db.commit()
    db.refresh(user)
    return TokenResponse(access_token=create_access_token(user), user=serialize_user(user))
