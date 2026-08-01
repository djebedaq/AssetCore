from __future__ import annotations

import io
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

import qrcode
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from .audit import add_audit_log
from .database import SessionLocal, get_db
from .document_generation import (
    build_daily_report_pdf,
    build_protocol_docx,
    build_protocol_pdf,
    safe_filename,
)
from .industrial_api import router as industrial_router
from .localization import normalize_language, translate
from .migrations import run_migrations
from .models import (
    AssetCategory,
    AuditLog,
    GeneratedDocument,
    Location,
    Machine,
    MachineStatus,
    PartCatalog,
    PartRequest,
    PartRequestLine,
    PartRequestStatus,
    Repair,
    RepairEvent,
    RepairEventType,
    RepairStatus,
    TechnicalDocument,
    TransferBatch,
    TransferProtocol,
    User,
    utcnow,
)
from .permissions import Permission, ensure_permission, is_observer, require_permission
from .schemas import (
    AuditLogOut,
    AvailabilityOut,
    BatchDetailsOut,
    BatchProgressOut,
    BatchSummaryOut,
    BulkIssueRequest,
    BulkIssueResponse,
    BulkReturnItem,
    BulkReturnRequest,
    BulkReturnResponse,
    LanguagePreferenceUpdate,
    LocationOut,
    LoginRequest,
    MachineCreate,
    MachineOut,
    MachineUpdate,
    PartCatalogOut,
    PartRequestCreate,
    PartRequestOut,
    RepairCreate,
    RepairOut,
    RepairUpdate,
    TechnicalDocumentOut,
    TokenResponse,
    TransferCreate,
    TransferOut,
    UserOut,
)
from .security import (
    create_access_token,
    get_authenticated_user,
    get_current_active_user,
    verify_password,
)
from .seed import seed_database
from .settings import settings
from .transfer_service import (
    TransferServiceError,
    availability,
    batch_details,
    batch_progress,
    bulk_issue,
    bulk_return,
    get_protocol_document,
    list_batches,
)
from .user_api import router as user_router
from .user_api import serialize_user
from .workflow import (
    REPAIR_TO_MACHINE_STATUS,
    add_machine_event,
    ensure_machine_transition,
    ensure_repair_can_complete,
    ensure_repair_transition,
)

ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / "resources"
DOCS_DIR = RESOURCES / "technical_docs"


@asynccontextmanager
async def lifespan(_: FastAPI):
    run_migrations()
    with SessionLocal() as db:
        seed_database(db)
    yield

app = FastAPI(
    title="AssetCore API",
    version="1.2.0-industrial-foundation",
    description=(
        "API за професионално индустриално управление на активи, защитени "
        "предавания, ремонти, документи и проследима история."
    ),
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://localhost:4173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(industrial_router)
app.include_router(user_router)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    language = normalize_language(request.headers.get("Accept-Language"))
    errors = []
    for error in exc.errors():
        message = str(error.get("msg", translate("validation.invalid", language)))
        if message.startswith("Value error, "):
            message = message.removeprefix("Value error, ")
        location = ".".join(str(part) for part in error.get("loc", ()) if part != "body")
        errors.append({"field": location or "request", "message": message})
    message = (
        errors[0]["message"]
        if errors
        else translate("validation.invalid", language)
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": {
                "code": "validation_error",
                "message": message,
                "errors": errors,
            }
        },
    )

def _raise_service_error(exc: TransferServiceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.as_detail()) from exc


require_transfer_admin = require_permission(Permission.TRANSFERS_CREATE)
require_transfer_return = require_permission(Permission.TRANSFERS_RETURN)
require_repair_creator = require_permission(Permission.REPAIRS_CREATE)
require_repair_operator = require_permission(Permission.REPAIRS_EDIT)
require_audit_reader = require_permission(Permission.AUDIT_VIEW_OPERATIONAL)
require_asset_viewer = require_permission(Permission.ASSETS_VIEW)
require_transfer_viewer = require_permission(Permission.TRANSFERS_VIEW)
require_repair_viewer = require_permission(Permission.REPAIRS_VIEW)
require_request_viewer = require_permission(Permission.REQUESTS_VIEW)
require_request_creator = require_permission(Permission.REQUESTS_CREATE)
require_parts_viewer = require_permission(Permission.PARTS_VIEW)
require_document_viewer = require_permission(Permission.DOCUMENTS_VIEW)
require_document_generator = require_permission(Permission.DOCUMENTS_GENERATE)


def _active_transfer(db: Session, machine_id: int) -> TransferProtocol | None:
    return db.scalar(
        select(TransferProtocol).where(
            TransferProtocol.machine_id == machine_id,
            TransferProtocol.is_active.is_(True),
        )
    )


def _transfer_with_relations(db: Session, transfer_id: int) -> TransferProtocol | None:
    return db.scalar(
        select(TransferProtocol)
        .options(
            joinedload(TransferProtocol.machine).joinedload(Machine.location),
            joinedload(TransferProtocol.batch),
        )
        .where(TransferProtocol.id == transfer_id)
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "AssetCore",
        "version": "1.2.0-industrial-foundation",
    }


@app.post("/api/auth/login", response_model=TokenResponse)
def login(
    data: LoginRequest, request: Request, db: Session = Depends(get_db)
) -> TokenResponse:
    normalized_email = data.email.strip().casefold()
    user = db.scalar(select(User).where(func.lower(User.email) == normalized_email))
    if not user or not verify_password(data.password, user.password_hash):
        language = normalize_language(request.headers.get("Accept-Language"))
        raise HTTPException(401, translate("auth.invalid_credentials", language))
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "account_inactive", "message": "Акаунтът е деактивиран."},
        )
    user.last_login_at = utcnow()
    user.updated_at = utcnow()
    db.commit()
    db.refresh(user)
    return TokenResponse(
        access_token=create_access_token(user),
        user=serialize_user(user),
    )


@app.get("/api/auth/me", response_model=UserOut)
def current_user(user: User = Depends(get_authenticated_user)) -> dict:
    return serialize_user(user)


@app.patch("/api/users/me/preferences", response_model=UserOut)
def update_user_preferences(
    data: LanguagePreferenceUpdate,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> User:
    previous_language = user.preferred_language
    user.preferred_language = data.preferred_language.value
    add_audit_log(
        db,
        user,
        "user_preference",
        user.id,
        "Променен предпочитан език",
        {
            "previous_language": previous_language,
            "new_language": user.preferred_language,
        },
    )
    db.commit()
    db.refresh(user)
    return serialize_user(user)


@app.get("/api/dashboard")
def dashboard(
    _: User = Depends(require_repair_viewer), db: Session = Depends(get_db)
) -> dict:
    total = db.scalar(select(func.count(Machine.id))) or 0
    by_status = dict(
        db.execute(select(Machine.status, func.count(Machine.id)).group_by(Machine.status)).all()
    )
    return {
        "total_machines": total,
        "ready": by_status.get(MachineStatus.READY.value, 0),
        "in_repair": sum(
            by_status.get(value, 0)
            for value in [
                MachineStatus.REPAIR.value,
                MachineStatus.INSPECTION.value,
                MachineStatus.WAITING_PARTS.value,
                MachineStatus.TESTING.value,
            ]
        ),
        "in_use": by_status.get(MachineStatus.IN_USE.value, 0)
        + by_status.get(MachineStatus.ISSUED.value, 0),
        "open_repairs": db.scalar(
            select(func.count(Repair.id)).where(Repair.closed_at.is_(None))
        )
        or 0,
        "pending_parts": db.scalar(
            select(func.count(PartRequest.id)).where(
                PartRequest.status.not_in(
                    [
                        PartRequestStatus.DELIVERED.value,
                        PartRequestStatus.CANCELLED.value,
                    ]
                )
            )
        )
        or 0,
        "protocols": db.scalar(select(func.count(TransferProtocol.id))) or 0,
        "documents": db.scalar(select(func.count(TechnicalDocument.id))) or 0,
        "status_breakdown": by_status,
        "recent_repairs": [
            {
                "id": repair.id,
                "machine": repair.machine.name,
                "problem": repair.reported_problem,
                "status": repair.status,
                "opened_at": repair.opened_at,
            }
            for repair in db.scalars(
                select(Repair)
                .options(joinedload(Repair.machine))
                .order_by(Repair.opened_at.desc())
                .limit(5)
            ).all()
        ],
    }


@app.get("/api/locations", response_model=list[LocationOut])
def locations(
    _: User = Depends(require_document_viewer), db: Session = Depends(get_db)
) -> list[Location]:
    return db.scalars(select(Location).order_by(Location.name)).all()


def _limited_machine(item: Machine) -> dict:
    return {
        "id": item.id,
        "inventory_number": item.inventory_number,
        "name": item.name,
        "brand": item.brand,
        "model": item.model,
        "status": item.status,
        "is_active": item.is_active,
        "location": (
            {"id": item.location.id, "name": item.location.name}
            if item.location
            else None
        ),
    }


@app.get("/api/machines", response_model=None)
def machines(
    user: User = Depends(require_asset_viewer), db: Session = Depends(get_db)
) -> list[Machine] | list[dict]:
    items = db.scalars(
        select(Machine)
        .options(joinedload(Machine.location))
        .order_by(Machine.pressure_bar.desc(), Machine.inventory_number)
    ).all()
    return [_limited_machine(item) for item in items] if is_observer(user) else items


@app.get("/api/machines/{machine_id}", response_model=None)
def machine(
    machine_id: int,
    user: User = Depends(require_asset_viewer),
    db: Session = Depends(get_db),
) -> Machine | dict:
    item = db.scalar(
        select(Machine)
        .options(joinedload(Machine.location))
        .where(Machine.id == machine_id)
    )
    if not item:
        raise HTTPException(404, "Машината не е намерена")
    return _limited_machine(item) if is_observer(user) else item


@app.post("/api/machines", response_model=MachineOut, status_code=201)
def create_machine(
    data: MachineCreate,
    user: User = Depends(require_permission(Permission.ASSETS_CREATE)),
    db: Session = Depends(get_db),
) -> Machine:
    if db.scalar(select(Machine).where(Machine.inventory_number == data.inventory_number)):
        raise HTTPException(409, "Дублиран инвентарен номер")
    category = db.get(AssetCategory, data.category_id) if data.category_id is not None else None
    if data.category_id is not None and category is None:
        raise HTTPException(404, "Категорията не е намерена")
    values = data.model_dump(mode="json")
    if category is not None:
        values["category"] = category.code
    item = Machine(**values)
    db.add(item)
    db.flush()
    add_machine_event(
        db,
        item,
        user,
        "MACHINE_CREATED",
        new_status=item.status,
        new_location_id=item.location_id,
        details={"inventory_number": item.inventory_number},
    )
    add_audit_log(db, user, "machine", item.id, "Създадена машина", values)
    db.commit()
    return db.scalar(
        select(Machine)
        .options(joinedload(Machine.location))
        .where(Machine.id == item.id)
    )


@app.patch("/api/machines/{machine_id}", response_model=MachineOut)
def update_machine(
    machine_id: int,
    data: MachineUpdate,
    user: User = Depends(require_permission(Permission.ASSETS_EDIT)),
    db: Session = Depends(get_db),
) -> Machine:
    item = db.get(Machine, machine_id)
    if not item:
        raise HTTPException(404, "Машината не е намерена")
    changes = data.model_dump(exclude_unset=True, mode="json")
    category = (
        db.get(AssetCategory, changes["category_id"])
        if changes.get("category_id") is not None
        else None
    )
    if changes.get("category_id") is not None and category is None:
        raise HTTPException(404, "Категорията не е намерена")
    active = _active_transfer(db, machine_id)
    if "status" in changes:
        requested_status = changes["status"]
        issued_statuses = {MachineStatus.ISSUED.value, MachineStatus.IN_USE.value}
        if active and requested_status not in issued_statuses:
            raise HTTPException(
                409,
                detail={
                    "code": "active_transfer_status_conflict",
                    "message": (
                        f"Статусът на машина №{item.inventory_number} не може да бъде "
                        f"сменен на „{requested_status}“, докато протокол "
                        f"{active.protocol_number} е активен."
                    ),
                },
            )
        if not active and requested_status in issued_statuses:
            raise HTTPException(
                409,
                detail={
                    "code": "missing_active_transfer",
                    "message": (
                        "Статус „Издадена“ или „В употреба“ се задава само чрез "
                        "защитена операция по издаване."
                    ),
                },
            )
        ensure_machine_transition(item.status, requested_status)
    before = {"status": item.status, "location_id": item.location_id}
    for key, value in changes.items():
        setattr(item, key, value)
    if category is not None:
        item.category = category.code
    item.updated_at = utcnow()
    add_machine_event(
        db,
        item,
        user,
        "MACHINE_UPDATED",
        previous_status=before["status"],
        new_status=item.status,
        previous_location_id=before["location_id"],
        new_location_id=item.location_id,
        details={"changed_fields": sorted(changes)},
    )
    add_audit_log(
        db,
        user,
        "machine",
        item.id,
        "Актуализирана машина",
        {"преди": before, "след": changes},
    )
    db.commit()
    return db.scalar(
        select(Machine)
        .options(joinedload(Machine.location))
        .where(Machine.id == item.id)
    )


@app.get("/api/machines/{machine_id}/qr")
def qr(
    machine_id: int,
    request: Request,
    _: User = Depends(require_document_generator),
    db: Session = Depends(get_db),
) -> Response:
    item = db.get(Machine, machine_id)
    if not item:
        raise HTTPException(404, "Машината не е намерена")
    base_url = (settings.public_base_url or str(request.base_url)).rstrip("/")
    image = qrcode.make(f"{base_url}/machine/{item.id}")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return Response(output.getvalue(), media_type="image/png")


@app.get("/api/repairs", response_model=list[RepairOut])
def repairs(
    _: User = Depends(require_repair_viewer), db: Session = Depends(get_db)
) -> list[Repair]:
    return db.scalars(
        select(Repair)
        .options(joinedload(Repair.machine).joinedload(Machine.location))
        .order_by(Repair.opened_at.desc())
    ).unique().all()


@app.post("/api/repairs", response_model=RepairOut, status_code=201)
def create_repair(
    data: RepairCreate,
    user: User = Depends(require_repair_creator),
    db: Session = Depends(get_db),
) -> Repair:
    machine_statement = select(Machine).where(Machine.id == data.machine_id)
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        machine_statement = machine_statement.with_for_update()
    item = db.scalar(machine_statement)
    if not item:
        raise HTTPException(404, "Машината не е намерена")
    active = _active_transfer(db, item.id)
    if active:
        raise HTTPException(
            409,
            detail={
                "code": "active_transfer_repair_conflict",
                "message": (
                    f"Машина №{item.inventory_number} е издадена по протокол "
                    f"{active.protocol_number} и първо трябва да бъде върната."
                ),
            },
        )
    if data.status.value != RepairStatus.ACCEPTED.value:
        raise HTTPException(
            409,
            detail={
                "code": "repair_must_start_as_accepted",
                "message": "Нов ремонт винаги започва от етап „Приемане“.",
            },
        )
    open_repair = db.scalar(
        select(Repair.id).where(
            Repair.machine_id == item.id,
            Repair.status != RepairStatus.COMPLETED.value,
        )
    )
    if open_repair:
        raise HTTPException(
            409,
            detail={
                "code": "open_repair_exists",
                "message": f"Машина №{item.inventory_number} вече има незавършен ремонт.",
            },
        )
    previous_status = item.status
    ensure_machine_transition(previous_status, MachineStatus.INSPECTION.value)
    repair = Repair(
        machine_id=item.id,
        reported_problem=data.reported_problem,
        diagnosis=data.diagnosis,
        work_performed=data.work_performed,
        result=data.result,
        status=RepairStatus.ACCEPTED.value,
        responsible_user_id=user.id,
        accepted_by_id=user.id,
    )
    db.add(repair)
    db.flush()
    repair.repair_reference = f"REP-{repair.opened_at:%Y}-{repair.id:06d}"
    item.status = MachineStatus.INSPECTION.value
    db.add(
        RepairEvent(
            repair_id=repair.id,
            event_type=RepairEventType.ACCEPTED.value,
            status_after=repair.status,
            description=data.reported_problem,
            user_id=user.id,
        )
    )
    add_machine_event(
        db,
        item,
        user,
        "REPAIR_ACCEPTED",
        reference=repair.repair_reference,
        previous_status=previous_status,
        new_status=item.status,
        details={"repair_id": repair.id},
    )
    add_audit_log(
        db,
        user,
        "repair",
        repair.id,
        "Приета машина за ремонт",
        {
            "machine": item.inventory_number,
            "repair_reference": repair.repair_reference,
            "problem": data.reported_problem,
            "previous_status": previous_status,
            "new_status": item.status,
        },
    )
    db.commit()
    return db.scalar(
        select(Repair)
        .options(joinedload(Repair.machine).joinedload(Machine.location))
        .where(Repair.id == repair.id)
    )


@app.patch("/api/repairs/{repair_id}", response_model=RepairOut)
def update_repair(
    repair_id: int,
    data: RepairUpdate,
    user: User = Depends(require_repair_operator),
    db: Session = Depends(get_db),
) -> Repair:
    if data.close or data.status == RepairStatus.COMPLETED:
        ensure_permission(user, Permission.REPAIRS_COMPLETE)
    repair = db.get(Repair, repair_id)
    if not repair:
        raise HTTPException(404, "Ремонтът не е намерен")
    changes = data.model_dump(
        exclude={"close", "status"}, exclude_unset=True, mode="json"
    )
    for key, value in changes.items():
        setattr(repair, key, value)
    previous_status = repair.status
    previous_machine_status = repair.machine.status
    if data.status is not None and data.status.value != repair.status:
        ensure_repair_transition(repair.status, data.status.value)
        if data.status.value == RepairStatus.COMPLETED.value:
            ensure_repair_can_complete(repair)
            repair.closed_at = utcnow()
        repair.status = data.status.value
        next_machine_status = REPAIR_TO_MACHINE_STATUS[repair.status]
        ensure_machine_transition(repair.machine.status, next_machine_status)
        repair.machine.status = next_machine_status
    if data.close:
        if repair.status != RepairStatus.TESTING.value:
            raise HTTPException(
                409,
                detail={
                    "code": "repair_testing_required",
                    "message": (
                        "Ремонтът може да бъде приключен само от етап „Тестване“. "
                        "Използвайте ремонтната карта за запис на прегледа и теста."
                    ),
                },
            )
        ensure_repair_can_complete(repair)
        repair.closed_at = utcnow()
        repair.status = RepairStatus.COMPLETED.value
        repair.machine.status = MachineStatus.READY.value
    db.add(
        RepairEvent(
            repair_id=repair.id,
            event_type=(
                RepairEventType.COMPLETED.value
                if data.close
                else RepairEventType.STATUS_CHANGE.value
            ),
            status_before=previous_status,
            status_after=repair.status,
            description="Обновена ремонтна карта през съвместимия API маршрут",
            user_id=user.id,
        )
    )
    if previous_machine_status != repair.machine.status:
        add_machine_event(
            db,
            repair.machine,
            user,
            "REPAIR_STATUS_CHANGED",
            reference=repair.repair_reference,
            previous_status=previous_machine_status,
            new_status=repair.machine.status,
            details={"repair_id": repair.id, "repair_status": repair.status},
        )
    add_audit_log(
        db,
        user,
        "repair",
        repair.id,
        "Актуализиран ремонт",
        {
            "previous_status": previous_status,
            "new_status": repair.status,
            "previous_machine_status": previous_machine_status,
            "new_machine_status": repair.machine.status,
            "changed_fields": sorted(data.model_fields_set),
        },
    )
    db.commit()
    return db.scalar(
        select(Repair)
        .options(joinedload(Repair.machine).joinedload(Machine.location))
        .where(Repair.id == repair.id)
    )


@app.get("/api/parts", response_model=list[PartRequestOut])
def parts(
    _: User = Depends(require_request_viewer), db: Session = Depends(get_db)
) -> list[PartRequest]:
    return db.scalars(
        select(PartRequest)
        .options(joinedload(PartRequest.machine).joinedload(Machine.location))
        .order_by(PartRequest.created_at.desc())
    ).all()


@app.post("/api/parts", response_model=PartRequestOut, status_code=201)
def create_part(
    data: PartRequestCreate,
    user: User = Depends(require_request_creator),
    db: Session = Depends(get_db),
) -> PartRequest:
    if data.status.value != PartRequestStatus.DRAFT.value:
        raise HTTPException(
            409,
            detail={
                "code": "part_request_must_start_as_draft",
                "message": "Новата заявка за части трябва да започне като чернова.",
            },
        )
    if data.machine_id is not None and db.get(Machine, data.machine_id) is None:
        raise HTTPException(404, "Машината не е намерена")
    request = PartRequest(
        machine_id=data.machine_id,
        part_name=data.part_name,
        part_number=data.part_number,
        quantity=data.quantity,
        reason=data.reason,
        priority=data.priority.value,
        status=PartRequestStatus.DRAFT.value,
        language=user.preferred_language,
        requested_by_id=user.id,
    )
    db.add(request)
    db.flush()
    request.request_reference = f"PR-{request.created_at:%Y}-{request.id:06d}"
    db.add(
        PartRequestLine(
            request_id=request.id,
            part_number=data.part_number,
            description=data.part_name,
            quantity=float(data.quantity),
            reason=data.reason,
        )
    )
    add_audit_log(
        db,
        user,
        "part_request",
        request.id,
        "Създадена заявка за части",
        {
            "request_reference": request.request_reference,
            "machine_id": request.machine_id,
            "line_count": 1,
            "status": request.status,
        },
    )
    db.commit()
    return db.scalar(
        select(PartRequest)
        .options(joinedload(PartRequest.machine).joinedload(Machine.location))
        .where(PartRequest.id == request.id)
    )


@app.get("/api/catalog/parts", response_model=list[PartCatalogOut])
def catalog(
    q: str = "",
    brand: str = "",
    _: User = Depends(require_parts_viewer),
    db: Session = Depends(get_db),
) -> list[PartCatalog]:
    statement = select(PartCatalog)
    if brand:
        statement = statement.where(PartCatalog.brand == brand)
    if q:
        statement = statement.where(
            or_(
                PartCatalog.part_number.ilike(f"%{q}%"),
                PartCatalog.alternative_part_number.ilike(f"%{q}%"),
                PartCatalog.name_bg.ilike(f"%{q}%"),
                PartCatalog.name_en.ilike(f"%{q}%"),
                PartCatalog.name_ru.ilike(f"%{q}%"),
                PartCatalog.original_name.ilike(f"%{q}%"),
                PartCatalog.description.ilike(f"%{q}%"),
                PartCatalog.assembly.ilike(f"%{q}%"),
                PartCatalog.position.ilike(f"%{q}%"),
            )
        )
    return db.scalars(
        statement.order_by(
            PartCatalog.brand, PartCatalog.assembly, PartCatalog.position
        ).limit(500)
    ).all()


@app.get("/api/transfers", response_model=list[TransferOut])
def transfers(
    _: User = Depends(require_transfer_viewer), db: Session = Depends(get_db)
) -> list[TransferProtocol]:
    return db.scalars(
        select(TransferProtocol)
        .options(
            joinedload(TransferProtocol.machine).joinedload(Machine.location),
            joinedload(TransferProtocol.batch),
        )
        .order_by(TransferProtocol.created_at.desc())
    ).unique().all()


@app.get("/api/transfers/availability", response_model=list[AvailabilityOut])
def transfer_availability(
    user: User = Depends(require_transfer_viewer), db: Session = Depends(get_db)
) -> list[dict]:
    return availability(db, user.preferred_language)


@app.post(
    "/api/transfers/bulk-issue",
    response_model=BulkIssueResponse,
    status_code=status.HTTP_201_CREATED,
)
def bulk_issue_endpoint(
    data: BulkIssueRequest,
    user: User = Depends(require_transfer_admin),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return bulk_issue(db, user, data)
    except TransferServiceError as exc:
        _raise_service_error(exc)


@app.post("/api/transfers/bulk-return", response_model=BulkReturnResponse)
def bulk_return_endpoint(
    data: BulkReturnRequest,
    user: User = Depends(require_transfer_return),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return bulk_return(db, user, data)
    except TransferServiceError as exc:
        _raise_service_error(exc)


@app.post("/api/transfers", response_model=TransferOut, status_code=201)
def create_transfer(
    data: TransferCreate,
    user: User = Depends(require_transfer_admin),
    db: Session = Depends(get_db),
) -> TransferProtocol:
    try:
        if data.protocol_type == "Предаване":
            result = bulk_issue(
                db,
                user,
                BulkIssueRequest(
                    machine_ids=[data.machine_id],
                    company_unit=data.company_unit,
                    department=data.department,
                    vessel=data.vessel,
                    dock=data.dock,
                    pier=data.pier,
                    work_area=data.work_area,
                    location_text=data.location_text,
                    location_id=data.location_id,
                    handed_over_by=data.handed_over_by,
                    accepted_by=data.accepted_by,
                    equipment=data.equipment,
                    hoses=data.hoses,
                    nozzles=data.nozzles,
                    guns=data.guns,
                    accessories=data.accessories,
                    condition_text=data.condition_text,
                    remarks=data.remarks,
                ),
            )
            transfer_id = result["transfers"][0]["transfer_id"]
        elif data.protocol_type in {"Приемане", "Връщане"}:
            ensure_permission(user, Permission.TRANSFERS_RETURN)
            active = _active_transfer(db, data.machine_id)
            if active is None:
                raise TransferServiceError(
                    409,
                    "return_without_active_transfer",
                    "Машината няма активно предаване и не може да бъде върната.",
                    {"machine_id": data.machine_id},
                )
            if not data.condition_text or not data.remarks:
                raise HTTPException(
                    422,
                    detail={
                        "code": "return_details_required",
                        "message": (
                            "За връщане са задължителни състояние и резултат "
                            "(поле „Забележки“ в стария API договор)."
                        ),
                    },
                )
            bulk_return(
                db,
                user,
                BulkReturnRequest(
                    items=[
                        BulkReturnItem(
                            transfer_id=active.id,
                            machine_id=data.machine_id,
                            condition_text=data.condition_text,
                            result_text=data.remarks,
                            returned_by=data.handed_over_by,
                            accepted_by=data.accepted_by,
                            location_id=data.location_id,
                            next_status=MachineStatus.INSPECTION,
                        )
                    ]
                ),
            )
            transfer_id = active.id
        else:
            raise HTTPException(
                422,
                detail={
                    "code": "invalid_transfer_type",
                    "message": "Неподдържан вид приемо-предавателна операция.",
                },
            )
    except TransferServiceError as exc:
        _raise_service_error(exc)
    transfer = _transfer_with_relations(db, transfer_id)
    assert transfer is not None
    return transfer


@app.get("/api/transfer-batches", response_model=list[BatchSummaryOut])
def transfer_batches(
    _: User = Depends(require_transfer_viewer), db: Session = Depends(get_db)
) -> list[dict]:
    return list_batches(db)


@app.get("/api/transfer-batches/{batch_id}", response_model=BatchDetailsOut)
def transfer_batch_details(
    batch_id: int,
    user: User = Depends(require_transfer_viewer),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return batch_details(db, batch_id, user.preferred_language)
    except TransferServiceError as exc:
        _raise_service_error(exc)


@app.get(
    "/api/transfer-batches/{batch_id}/progress", response_model=BatchProgressOut
)
def transfer_batch_progress(
    batch_id: int,
    user: User = Depends(require_transfer_viewer),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return batch_progress(db, batch_id, user.preferred_language)
    except TransferServiceError as exc:
        _raise_service_error(exc)


@app.get("/api/protocol-documents/{document_id}/download")
def protocol_document_download(
    document_id: int,
    user: User = Depends(require_document_viewer),
    db: Session = Depends(get_db),
) -> Response:
    try:
        document = get_protocol_document(db, document_id, user.preferred_language)
    except TransferServiceError as exc:
        _raise_service_error(exc)
    return Response(
        document.content,
        media_type=document.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{document.filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/api/transfer-batches/{batch_id}/documents.zip")
def batch_documents_zip(
    batch_id: int,
    _: User = Depends(require_document_viewer),
    db: Session = Depends(get_db),
) -> Response:
    batch = db.scalar(
        select(TransferBatch)
        .options(selectinload(TransferBatch.documents))
        .where(TransferBatch.id == batch_id)
    )
    if batch is None:
        raise HTTPException(404, "Партидата не е намерена")
    generated = db.scalars(
        select(GeneratedDocument).where(GeneratedDocument.batch_id == batch.id)
    ).all()
    if not batch.documents and not generated:
        raise HTTPException(404, "Партидата няма генерирани протоколи")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for document in sorted(batch.documents, key=lambda item: item.filename):
            archive.writestr(safe_filename(document.filename), document.content)
        for document in sorted(generated, key=lambda item: item.filename):
            archive.writestr(safe_filename(document.filename), document.content)
    filename = f"{safe_filename(batch.batch_reference)}-protocols.zip"
    return Response(
        output.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


def _legacy_protocol_response(
    transfer_id: int, format_name: str, db: Session
) -> Response:
    transfer = db.scalar(
        select(TransferProtocol)
        .options(
            joinedload(TransferProtocol.machine),
            joinedload(TransferProtocol.batch),
            selectinload(TransferProtocol.documents),
        )
        .where(TransferProtocol.id == transfer_id)
    )
    if not transfer:
        raise HTTPException(404, "Протоколът не е намерен")
    stored = next(
        (document for document in transfer.documents if document.format == format_name),
        None,
    )
    if stored:
        return Response(
            stored.content,
            media_type=stored.media_type,
            headers={"Content-Disposition": f'attachment; filename="{stored.filename}"'},
        )
    batch_reference = transfer.batch_reference or "-"
    if format_name == "docx":
        content = build_protocol_docx(transfer, batch_reference)
        media_type = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
    else:
        content = build_protocol_pdf(transfer, batch_reference)
        media_type = "application/pdf"
    filename = f"{safe_filename(transfer.protocol_number)}.{format_name}"
    return Response(
        content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/transfers/{transfer_id}/docx")
def protocol_docx(
    transfer_id: int,
    _: User = Depends(require_document_viewer),
    db: Session = Depends(get_db),
) -> Response:
    return _legacy_protocol_response(transfer_id, "docx", db)


@app.get("/api/transfers/{transfer_id}/pdf")
def protocol_pdf(
    transfer_id: int,
    _: User = Depends(require_document_viewer),
    db: Session = Depends(get_db),
) -> Response:
    return _legacy_protocol_response(transfer_id, "pdf", db)


@app.get("/api/documents", response_model=list[TechnicalDocumentOut])
def documents(
    _: User = Depends(require_document_viewer), db: Session = Depends(get_db)
) -> list[TechnicalDocument]:
    return db.scalars(
        select(TechnicalDocument).order_by(
            TechnicalDocument.brand,
            TechnicalDocument.category,
            TechnicalDocument.title,
        )
    ).all()


@app.get("/api/documents/{doc_id}/download")
def download_doc(
    doc_id: int,
    _: User = Depends(require_document_viewer),
    db: Session = Depends(get_db),
) -> FileResponse:
    document = db.get(TechnicalDocument, doc_id)
    if not document:
        raise HTTPException(404, "Документът не е намерен")
    path = (DOCS_DIR / document.file_path).resolve()
    if DOCS_DIR.resolve() not in path.parents or not path.is_file():
        raise HTTPException(404, "Файлът липсва")
    return FileResponse(path, filename=path.name)


@app.get("/api/audit", response_model=list[AuditLogOut])
def audit(
    _: User = Depends(require_audit_reader), db: Session = Depends(get_db)
) -> list[AuditLog]:
    return db.scalars(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(500)
    ).all()


@app.get("/api/reports/daily.pdf")
def daily_report(
    _: User = Depends(require_audit_reader), db: Session = Depends(get_db)
) -> Response:
    repairs = db.scalars(
        select(Repair)
        .options(joinedload(Repair.machine))
        .order_by(Repair.opened_at.desc())
        .limit(30)
    ).all()
    return Response(
        build_daily_report_pdf(repairs),
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="assetcore-daily-report.pdf"'
        },
    )


frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str) -> FileResponse:
        path = frontend_dist / full_path
        return FileResponse(path if path.is_file() else frontend_dist / "index.html")
