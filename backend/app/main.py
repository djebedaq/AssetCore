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
from .localization import normalize_language, translate
from .migrations import run_migrations
from .models import (
    AuditLog,
    Location,
    Machine,
    MachineStatus,
    PartCatalog,
    PartRequest,
    PartRequestStatus,
    Repair,
    RepairStatus,
    TechnicalDocument,
    TransferBatch,
    TransferProtocol,
    User,
    UserRole,
    utcnow,
)
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
from .security import create_access_token, get_current_user, verify_password
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


def require_transfer_admin(user: User = Depends(get_current_user)) -> User:
    if user.role not in {UserRole.ADMIN.value, UserRole.MANAGER.value}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "transfer_permission_denied",
                "message": translate("permission.transfer", user.preferred_language),
            },
        )
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "permission_denied",
                "message": translate("permission.denied", user.preferred_language),
            },
        )
    return user


def require_repair_operator(user: User = Depends(get_current_user)) -> User:
    if user.role not in {UserRole.ADMIN.value, UserRole.MECHANIC.value}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "permission_denied",
                "message": translate("permission.denied", user.preferred_language),
            },
        )
    return user


def require_audit_reader(user: User = Depends(get_current_user)) -> User:
    if user.role not in {
        UserRole.ADMIN.value,
        UserRole.APPROVER.value,
        UserRole.VIEWER.value,
    }:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "permission_denied",
                "message": translate("permission.denied", user.preferred_language),
            },
        )
    return user


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
    user = db.scalar(select(User).where(User.email == data.email))
    if not user or not verify_password(data.password, user.password_hash):
        language = normalize_language(request.headers.get("Accept-Language"))
        raise HTTPException(401, translate("auth.invalid_credentials", language))
    return TokenResponse(
        access_token=create_access_token(user),
        user={
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
            "preferred_language": user.preferred_language,
        },
    )


@app.get("/api/auth/me", response_model=UserOut)
def current_user(user: User = Depends(get_current_user)) -> User:
    return user


@app.patch("/api/users/me/preferences", response_model=UserOut)
def update_user_preferences(
    data: LanguagePreferenceUpdate,
    user: User = Depends(get_current_user),
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
    return user


@app.get("/api/dashboard")
def dashboard(
    _: User = Depends(get_current_user), db: Session = Depends(get_db)
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
    _: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[Location]:
    return db.scalars(select(Location).order_by(Location.name)).all()


@app.get("/api/machines", response_model=list[MachineOut])
def machines(
    _: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[Machine]:
    return db.scalars(
        select(Machine)
        .options(joinedload(Machine.location))
        .order_by(Machine.pressure_bar.desc(), Machine.inventory_number)
    ).all()


@app.get("/api/machines/{machine_id}", response_model=MachineOut)
def machine(
    machine_id: int,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Machine:
    item = db.scalar(
        select(Machine)
        .options(joinedload(Machine.location))
        .where(Machine.id == machine_id)
    )
    if not item:
        raise HTTPException(404, "Машината не е намерена")
    return item


@app.post("/api/machines", response_model=MachineOut, status_code=201)
def create_machine(
    data: MachineCreate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Machine:
    if db.scalar(select(Machine).where(Machine.inventory_number == data.inventory_number)):
        raise HTTPException(409, "Дублиран инвентарен номер")
    values = data.model_dump(mode="json")
    item = Machine(**values)
    db.add(item)
    db.flush()
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
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Machine:
    item = db.get(Machine, machine_id)
    if not item:
        raise HTTPException(404, "Машината не е намерена")
    changes = data.model_dump(exclude_unset=True, mode="json")
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
    before = {"status": item.status, "location_id": item.location_id}
    for key, value in changes.items():
        setattr(item, key, value)
    item.updated_at = utcnow()
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
def qr(machine_id: int, db: Session = Depends(get_db)) -> Response:
    item = db.get(Machine, machine_id)
    if not item:
        raise HTTPException(404, "Машината не е намерена")
    image = qrcode.make(f"assetcore://machine/{item.id}")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return Response(output.getvalue(), media_type="image/png")


@app.get("/api/repairs", response_model=list[RepairOut])
def repairs(
    _: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[Repair]:
    return db.scalars(
        select(Repair)
        .options(joinedload(Repair.machine).joinedload(Machine.location))
        .order_by(Repair.opened_at.desc())
    ).unique().all()


@app.post("/api/repairs", response_model=RepairOut, status_code=201)
def create_repair(
    data: RepairCreate,
    user: User = Depends(require_repair_operator),
    db: Session = Depends(get_db),
) -> Repair:
    item = db.get(Machine, data.machine_id)
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
    repair = Repair(**data.model_dump(mode="json"))
    item.status = MachineStatus.REPAIR.value
    db.add(repair)
    db.flush()
    add_audit_log(
        db,
        user,
        "repair",
        repair.id,
        "Приета машина за ремонт",
        {"machine": item.inventory_number, "problem": data.reported_problem},
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
    repair = db.get(Repair, repair_id)
    if not repair:
        raise HTTPException(404, "Ремонтът не е намерен")
    changes = data.model_dump(exclude={"close"}, exclude_unset=True, mode="json")
    for key, value in changes.items():
        setattr(repair, key, value)
    if data.close:
        requested_status = data.status.value if data.status else repair.status
        if requested_status != RepairStatus.TESTING.value or not (
            data.result or repair.result
        ):
            raise HTTPException(
                409,
                detail={
                    "code": "repair_testing_required",
                    "message": (
                        "Ремонтът може да бъде приключен като готов само след статус "
                        "„Тестване“ и записан резултат от теста."
                    ),
                },
            )
        repair.closed_at = utcnow()
        repair.status = RepairStatus.COMPLETED.value
        repair.machine.status = MachineStatus.READY.value
    add_audit_log(
        db, user, "repair", repair.id, "Актуализиран ремонт", data.model_dump()
    )
    db.commit()
    return db.scalar(
        select(Repair)
        .options(joinedload(Repair.machine).joinedload(Machine.location))
        .where(Repair.id == repair.id)
    )


@app.get("/api/parts", response_model=list[PartRequestOut])
def parts(
    _: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[PartRequest]:
    return db.scalars(
        select(PartRequest)
        .options(joinedload(PartRequest.machine).joinedload(Machine.location))
        .order_by(PartRequest.created_at.desc())
    ).all()


@app.post("/api/parts", response_model=PartRequestOut, status_code=201)
def create_part(
    data: PartRequestCreate,
    user: User = Depends(require_repair_operator),
    db: Session = Depends(get_db),
) -> PartRequest:
    request = PartRequest(**data.model_dump(mode="json"))
    db.add(request)
    db.flush()
    add_audit_log(
        db,
        user,
        "part_request",
        request.id,
        "Създадена заявка за части",
        data.model_dump(),
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
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PartCatalog]:
    statement = select(PartCatalog)
    if brand:
        statement = statement.where(PartCatalog.brand == brand)
    if q:
        statement = statement.where(
            or_(
                PartCatalog.part_number.ilike(f"%{q}%"),
                PartCatalog.description.ilike(f"%{q}%"),
                PartCatalog.assembly.ilike(f"%{q}%"),
            )
        )
    return db.scalars(
        statement.order_by(
            PartCatalog.brand, PartCatalog.assembly, PartCatalog.position
        ).limit(500)
    ).all()


@app.get("/api/transfers", response_model=list[TransferOut])
def transfers(
    _: User = Depends(get_current_user), db: Session = Depends(get_db)
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
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
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
    user: User = Depends(require_transfer_admin),
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
                    vessel=data.vessel,
                    location_text=data.location_text,
                    location_id=data.location_id,
                    handed_over_by=data.handed_over_by,
                    accepted_by=data.accepted_by,
                    equipment=data.equipment,
                    condition_text=data.condition_text,
                    remarks=data.remarks,
                ),
            )
            transfer_id = result["transfers"][0]["transfer_id"]
        elif data.protocol_type in {"Приемане", "Връщане"}:
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
    _: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[dict]:
    return list_batches(db)


@app.get("/api/transfer-batches/{batch_id}", response_model=BatchDetailsOut)
def transfer_batch_details(
    batch_id: int,
    user: User = Depends(get_current_user),
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
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return batch_progress(db, batch_id, user.preferred_language)
    except TransferServiceError as exc:
        _raise_service_error(exc)


@app.get("/api/protocol-documents/{document_id}/download")
def protocol_document_download(
    document_id: int,
    user: User = Depends(get_current_user),
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
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    batch = db.scalar(
        select(TransferBatch)
        .options(selectinload(TransferBatch.documents))
        .where(TransferBatch.id == batch_id)
    )
    if batch is None:
        raise HTTPException(404, "Партидата не е намерена")
    if not batch.documents:
        raise HTTPException(404, "Партидата няма генерирани протоколи")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for document in sorted(batch.documents, key=lambda item: item.filename):
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
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    return _legacy_protocol_response(transfer_id, "docx", db)


@app.get("/api/transfers/{transfer_id}/pdf")
def protocol_pdf(
    transfer_id: int,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    return _legacy_protocol_response(transfer_id, "pdf", db)


@app.get("/api/documents", response_model=list[TechnicalDocumentOut])
def documents(
    _: User = Depends(get_current_user), db: Session = Depends(get_db)
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
    _: User = Depends(get_current_user),
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
    _: User = Depends(get_current_user), db: Session = Depends(get_db)
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
