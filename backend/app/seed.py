import hashlib
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    AssetCategory,
    DocumentTemplate,
    DocumentTemplateVersion,
    DocumentType,
    LanguageCode,
    Location,
    Machine,
    MachineStatus,
    TechnicalDocument,
    TechnicalDocumentRevision,
    InstallationOwnership,
    ProfileStatus,
    SignatureSlot,
    User,
    UserRole,
    utcnow,
)
from .catalog_import import import_verified_catalog
from .security import hash_password
from .settings import settings

LOCATIONS = [
    "Цех",
    "Сух док",
    "Док 2",
    "Док 3",
    "Кей 1",
    "Кей 4",
    "Кей 6",
    "На борда на кораб",
    "Хамбар на кораб",
    "Склад",
    "Външен обект",
    "Не е определено",
]

# Проверен начален регистър, възстановен от протоколи, снимки и наличната база.
# Системата засега съдържа САМО HPWJ машини.
MACHINES = [
    {"inventory_number": "4", "brand": "CombiJet", "model": "JE60-500", "pressure_bar": 500, "serial_number": None},
    {"inventory_number": "5", "brand": "CombiJet", "model": "JE60-500", "pressure_bar": 500, "serial_number": None},
    {"inventory_number": "7", "brand": "Falch", "model": "Wheel Jet 30-e", "pressure_bar": 1000, "serial_number": "G41200143"},
    {"inventory_number": "9", "brand": "Falch", "model": "Wheel Jet 15-e", "pressure_bar": 500, "serial_number": "G39300296"},
    {"inventory_number": "10", "brand": "Falch", "model": "Wheel Jet 15-e", "pressure_bar": 500, "serial_number": "G39300297"},
    {"inventory_number": "11", "brand": "Falch", "model": "Wheel Jet 15-e", "pressure_bar": 500, "serial_number": "G39300298"},
    {"inventory_number": "12", "brand": "Falch", "model": "Wheel Jet 15-e", "pressure_bar": 500, "serial_number": "G39300299"},
    {"inventory_number": "13", "brand": "Falch", "model": "Wheel Jet 15-e", "pressure_bar": 500, "serial_number": "G39300415"},
    {"inventory_number": "14", "brand": "Falch", "model": "Wheel Jet 15-e", "pressure_bar": 500, "serial_number": "G39300416"},
    {"inventory_number": "15", "brand": "Falch", "model": "Wheel Jet 15-e", "pressure_bar": 500, "serial_number": "G39300417"},
    {"inventory_number": "16", "brand": "Falch", "model": "Wheel Jet 15-e", "pressure_bar": 500, "serial_number": "G39300418"},
    {"inventory_number": "17", "brand": "Falch", "model": "Wheel Jet 30-e", "pressure_bar": 1000, "serial_number": "G41200203"},
    {"inventory_number": "18", "brand": "Falch", "model": "Wheel Jet 30-e", "pressure_bar": 1000, "serial_number": "G41200204"},
    {"inventory_number": "19", "brand": "Самоделна", "model": "HPWJ – Falch съвместима", "pressure_bar": 500, "serial_number": None},
    {"inventory_number": "20", "brand": "HYDWIN (Fussen)", "model": "FCE15/50", "pressure_bar": 500, "serial_number": "2512005"},
    {"inventory_number": "21", "brand": "HYDWIN (Fussen)", "model": "FCE15/50", "pressure_bar": 500, "serial_number": "2512004"},
    {"inventory_number": "22", "brand": "HYDWIN (Fussen)", "model": "FCE15/50", "pressure_bar": 500, "serial_number": "2512001"},
    {"inventory_number": "23", "brand": "HYDWIN (Fussen)", "model": "FCE15/50", "pressure_bar": 500, "serial_number": "2512003"},
    {"inventory_number": "24", "brand": "HYDWIN (Fussen)", "model": "FCE15/50", "pressure_bar": 500, "serial_number": "2512002"},
]


def _seed_verified_registry(db: Session) -> None:
    configured_owner_email = settings.owner_email or settings.assetcore_owner_email
    if not configured_owner_email or not configured_owner_email.strip():
        raise RuntimeError(
            "OWNER_EMAIL (или съвместимата ASSETCORE_OWNER_EMAIL) е задължителна настройка."
        )
    owner_email = configured_owner_email.strip().casefold()
    local_part, separator, domain = owner_email.partition("@")
    if (
        not local_part
        or separator != "@"
        or not domain
        or "." not in domain
        or any(character.isspace() for character in owner_email)
    ):
        raise RuntimeError(
            "ASSETCORE_OWNER_EMAIL трябва да съдържа валиден служебен имейл адрес."
        )
    users = list(db.scalars(select(User).order_by(User.id)))
    ownership = db.scalar(select(InstallationOwnership).order_by(InstallationOwnership.id))
    if not users:
        initial_password = settings.owner_initial_password or settings.admin_password
        if not initial_password:
            raise RuntimeError(
                "OWNER_INITIAL_PASSWORD е задължителна при създаване на първия собственик."
            )
        owner_names = [settings.owner_first_name, settings.owner_middle_name, settings.owner_last_name]
        display_name = " ".join(value.strip() for value in owner_names if value and value.strip())
        owner = User(
            email=owner_email,
            full_name=display_name or "Администратор",
            first_name=settings.owner_first_name,
            middle_name=settings.owner_middle_name,
            last_name=settings.owner_last_name,
            job_title=settings.owner_job_title,
            profile_status=(
                ProfileStatus.COMPLETE.value
                if all(owner_names) and settings.owner_job_title
                else ProfileStatus.INCOMPLETE.value
            ),
            password_hash=hash_password(initial_password),
            role=UserRole.ADMINISTRATOR.value,
            is_active=True,
            is_system_owner=True,
            must_change_password=bool(settings.owner_initial_password),
        )
        db.add(owner)
        db.flush()
    elif ownership is not None:
        owner = db.get(User, ownership.owner_user_id)
        if owner is None or not owner.is_active or owner.role != UserRole.ADMINISTRATOR.value:
            raise RuntimeError(
                "Защитеното обозначение на собственика сочи към липсващ, неактивен "
                "или неадминистраторски акаунт."
            )
        for user in users:
            user.is_system_owner = user.id == owner.id
    else:
        matches = [user for user in users if user.email.strip().casefold() == owner_email]
        owners = [user for user in users if user.is_system_owner]
        if len(matches) != 1 or (owners and owners != matches):
            raise RuntimeError(
                "Не може безопасно да се определи точно един системен собственик. "
                "Задайте ASSETCORE_OWNER_EMAIL към съществуващ уникален акаунт."
            )
        owner = matches[0]
        owner.email = owner_email
        owner.role = UserRole.ADMINISTRATOR.value
        owner.is_active = True
        owner.is_system_owner = True

    if ownership is None:
        db.add(
            InstallationOwnership(
                owner_user_id=owner.id,
                designated_by_id=owner.id,
                transfer_reason="Първоначално определяне от конфигурацията на инсталацията.",
            )
        )

    existing_locations = {x.name: x for x in db.scalars(select(Location)).all()}
    for name in LOCATIONS:
        if name not in existing_locations:
            db.add(Location(name=name))
        elif name == "Цех" and not existing_locations[name].is_active:
            existing_locations[name].is_active = True
    db.commit()

    default_signature_slots = (
        (DocumentType.TRANSFER_ISSUE.value, "ACCEPTANCE", "Приел", "Accepted by", "Принял", 1),
        (DocumentType.TRANSFER_ISSUE.value, "HANDOVER", "Предал", "Handed over by", "Передал", 2),
        (DocumentType.TRANSFER_RETURN.value, "RETURNED_BY", "Върнал", "Returned by", "Вернул", 1),
        (DocumentType.TRANSFER_RETURN.value, "ACCEPTED_RETURN", "Приел връщането", "Return accepted by", "Принял возврат", 2),
        (DocumentType.PART_REQUEST.value, "REQUESTED_BY", "Заявил", "Requested by", "Заявил", 1),
        (DocumentType.PART_REQUEST.value, "APPROVED_BY", "Одобрил", "Approved by", "Утвердил", 2),
    )
    existing_slots = {(slot.document_type, slot.code) for slot in db.scalars(select(SignatureSlot))}
    for document_type, code, bg, en, ru, sequence in default_signature_slots:
        if (document_type, code) not in existing_slots:
            db.add(SignatureSlot(document_type=document_type, code=code, label_bg=bg, label_en=en, label_ru=ru, sequence=sequence, signing_mode="SEQUENTIAL"))
    for slot in db.scalars(
        select(SignatureSlot).where(
            SignatureSlot.document_type == DocumentType.REPAIR_PROTOCOL.value
        )
    ):
        slot.required = False
        slot.is_active = False
    db.commit()

    locations = {x.name: x for x in db.scalars(select(Location)).all()}
    hpwj_category = db.scalar(
        select(AssetCategory).where(AssetCategory.code == "HPWJ")
    )
    if hpwj_category is None:
        hpwj_category = AssetCategory(
            code="HPWJ",
            name_bg="Водоструйни машини с високо налягане",
            name_en="High-pressure water jet machines",
            name_ru="Водоструйные машины высокого давления",
            description="Проверена категория за наличния HPWJ регистър.",
        )
        db.add(hpwj_category)
        db.flush()
    existing = {m.inventory_number: m for m in db.scalars(select(Machine)).all()}
    for item in MACHINES:
        machine = existing.get(item["inventory_number"])
        if machine is None:
            machine = Machine(
                inventory_number=item["inventory_number"],
                name=f"HPWJ №{item['inventory_number']}",
                category="HPWJ",
                status=MachineStatus.READY.value,
                location_id=locations["Цех"].id,
            )
            db.add(machine)
        machine.name = f"HPWJ №{item['inventory_number']}"
        machine.category = "HPWJ"
        machine.category_id = hpwj_category.id
        machine.brand = item["brand"]
        machine.model = item["model"]
        machine.pressure_bar = item["pressure_bar"]
        machine.serial_number = item["serial_number"]
        if machine.location_id is None:
            machine.location_id = locations["Цех"].id
    db.commit()

# --- Director Preview: technical library and verified catalog records ---
def _seed_documents_and_catalog(db: Session) -> None:
    root = Path(__file__).resolve().parents[1] / 'resources' / 'technical_docs'
    if root.exists():
        for path in sorted(p for p in root.rglob('*') if p.is_file()):
            rel = path.relative_to(root).as_posix()
            brand_folder = rel.split('/')[0].lower()
            brand = {'falch500':'Falch','falch1000':'Falch','hydwin':'HYDWIN (Fussen)','combijet':'CombiJet','protocols_hpwj':'HPWJ протоколи','parts_requests_hpwj':'HPWJ заявки'}.get(brand_folder, brand_folder)
            model = {'falch500':'Wheel Jet 15-e','falch1000':'Wheel Jet 30-e','hydwin':'FCE15/50','combijet':'JE60-500'}.get(brand_folder)
            linked_numbers = {'falch500':['9','10','11','12','13','14','15','16','19'],'falch1000':['7','17','18'],'hydwin':['20','21','22','23','24'],'combijet':['4','5']}.get(brand_folder)
            suffix = path.suffix.lower()
            if brand_folder == 'protocols_hpwj':
                category = 'Реални протоколи преди/след ремонт'
            elif brand_folder == 'parts_requests_hpwj':
                category = 'Реални заявки за резервни части'
            elif suffix == '.pdf':
                category = 'Parts list / ръководство'
            else:
                category = 'Работен документ'
            if not db.scalar(select(TechnicalDocument).where(TechnicalDocument.file_path == rel)):
                db.add(TechnicalDocument(brand=brand, model=model, category=category, title=path.name, file_path=rel, linked_machine_numbers=linked_numbers))
            else:
                document = db.scalar(select(TechnicalDocument).where(TechnicalDocument.file_path == rel))
                if document is not None:
                    document.brand = brand
                    document.model = model
                    document.linked_machine_numbers = linked_numbers
    db.commit()

    for document in db.scalars(select(TechnicalDocument)).all():
        path = root / document.file_path
        if not path.is_file():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        document.sha256 = digest
        document.uploaded_filename = document.title
        document.created_at = document.created_at or utcnow()
        if not db.scalar(
            select(TechnicalDocumentRevision).where(
                TechnicalDocumentRevision.document_id == document.id,
                TechnicalDocumentRevision.version == 1,
            )
        ):
            document.revisions.append(
                TechnicalDocumentRevision(
                    version=1,
                    revision_label=document.revision,
                    filename=path.name,
                    media_type="application/octet-stream",
                    file_path=document.file_path,
                    sha256=digest,
                    change_note="Първоначално проверено файлово копие от техническата библиотека.",
                )
            )
    db.commit()

    admin = db.scalar(select(User).where(User.is_system_owner.is_(True)))
    if admin:
        import_verified_catalog(db, admin)
        db.commit()


def _seed_document_templates(db: Session) -> None:
    from .template_engine import validate_template

    admin = db.scalar(select(User).where(User.is_system_owner.is_(True)))
    if admin is None:
        return
    resources = Path(__file__).resolve().parents[1] / "resources"
    references = [
        {
            "code": "HPWJ_TRANSFER_ISSUE",
            "document_type": DocumentType.TRANSFER_ISSUE.value,
            "name_bg": "Протокол за предаване на миеща техника",
            "name_en": "High-pressure washing equipment issue protocol",
            "name_ru": "Протокол выдачи моечной техники высокого давления",
            "template_stem": "transfer_issue",
            "template_version": 3,
            "required_fields": ["MACHINE_NUMBER", "SERIAL_NUMBER", "CONDITION_TEXT"],
            "contract": {
                "page": "A4 portrait",
                "header": "KRZ / ODESSOS / AssetCore",
                "sections": ["protocol_number", "machine_identity", "ten_point_checklist", "usage", "signatures"],
                "reference_only": False,
                "reference_photos": ["reference_photos/IMG_5811.jpeg", "reference_photos/IMG_5812.jpeg"],
            },
        },
        {
            "code": "HPWJ_TRANSFER_RETURN",
            "document_type": DocumentType.TRANSFER_RETURN.value,
            "name_bg": "Протокол за приемане на миеща техника след използване",
            "name_en": "High-pressure washing equipment return protocol",
            "name_ru": "Протокол возврата моечной техники после использования",
            "template_stem": "transfer_return",
            "template_version": 3,
            "required_fields": ["MACHINE_NUMBER", "SERIAL_NUMBER", "CONDITION_TEXT"],
            "contract": {
                "page": "A4 portrait",
                "header": "KRZ / ODESSOS / AssetCore",
                "sections": ["protocol_number", "machine_identity", "ten_point_checklist", "usage", "signatures"],
                "reference_only": False,
                "reference_photos": ["reference_photos/IMG_5813.jpeg", "reference_photos/IMG_5814.jpeg"],
            },
        },
        {
            "code": "HPWJ_REPAIR_PROTOCOL",
            "document_type": DocumentType.REPAIR_PROTOCOL.value,
            "name_bg": "Вътрешен протокол за извършен ремонт",
            "name_en": "Internal completed repair protocol",
            "name_ru": "Внутренний протокол выполненного ремонта",
            "template_stem": "repair_protocol",
            "template_version": 5,
            "required_fields": [
                "MACHINE_NUMBER", "REPAIR_REFERENCE", "CONDITION_BEFORE",
                "REQUIRED_WORK", "DIAGNOSIS", "DIAGNOSIS_DURATION",
                "WORK_PERFORMED", "REPAIR_DURATION", "TESTING_DURATION",
                "TEST_RESULT", "FINAL_RESULT", "TOTAL_WORK_DURATION",
            ],
            "contract": {
                "page": "A4 portrait",
                "header": "approved transfer_issue v3 company header",
                "sections": [
                    "repair_acceptance", "machine_identity", "condition_before",
                    "required_repair", "disassembly", "diagnosis", "required_parts",
                    "diagnosis_duration", "repair_actions", "parts_used",
                    "actual_work_time", "test", "condition_after", "repair_acceptance_signoff",
                ],
                "reference_only": False,
                "controlled_reference": "Топтоптоп.docx (content only; original retained outside repository)",
                "approved_header_source": "templates/transfer_issue-bg-v3.docx",
            },
        },
        {
            "code": "HPWJ_PART_REQUEST",
            "document_type": DocumentType.PART_REQUEST.value,
            "name_bg": "Техническа спецификация за доставка на резервни части",
            "name_en": "Technical specification for spare-parts supply",
            "name_ru": "Техническая спецификация на поставку запасных частей",
            "template_stem": "part_request",
            "template_version": 2,
            "required_fields": ["MACHINE_NUMBER", "REMARKS", "DECISION"],
            "contract": {
                "page": "A4 portrait",
                "sections": ["technical_specification_title", "machine_identity", "parts_table", "remarks", "request_reference_date_requester"],
                "reference_only": False,
                "controlled_reference": "technical_docs/parts_requests_hpwj/KK 1001 FALCH 500.docx",
            },
        },
    ]
    for definition in references:
        template = db.scalar(
            select(DocumentTemplate).where(
                DocumentTemplate.document_type == definition["document_type"],
                DocumentTemplate.code == definition["code"],
            )
        )
        if template is None:
            template = DocumentTemplate(
                code=definition["code"],
                document_type=definition["document_type"],
                name_bg=definition["name_bg"],
                name_en=definition["name_en"],
                name_ru=definition["name_ru"],
            )
            db.add(template)
            db.flush()
        for language in LanguageCode:
            template_version = definition["template_version"]
            source_path = f"templates/{definition['template_stem']}-{language.value}-v{template_version}.docx"
            source = resources / source_path
            if not source.is_file():
                raise RuntimeError(f"Липсва контролиран шаблон: {source_path}")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            existing = db.scalar(
                select(DocumentTemplateVersion).where(
                    DocumentTemplateVersion.template_id == template.id,
                    DocumentTemplateVersion.version == template_version,
                    DocumentTemplateVersion.language == language.value,
                )
            )
            if existing is None:
                existing = DocumentTemplateVersion(
                    template_id=template.id,
                    version=template_version,
                    language=language.value,
                    source_path=source_path,
                    source_filename=source.name,
                    source_media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    source_sha256=digest,
                    layout_contract=definition["contract"],
                    required_fields=definition["required_fields"],
                    numbering_rule="AssetCore deterministic business reference",
                    change_note="Машинно използваем шаблон, създаден по контролирания снимков образец.",
                    created_by_id=admin.id,
                )
                report = validate_template(existing)
                if not report["valid"]:
                    raise RuntimeError("Невалиден начален шаблон: " + "; ".join(report["errors"]))
                existing.validation_status = "PASSED"
                existing.validation_report = report
                existing.validated_at = utcnow()
                existing.validated_by_id = admin.id
                db.add(existing)
            db.query(DocumentTemplateVersion).filter(
                DocumentTemplateVersion.template_id == template.id,
                DocumentTemplateVersion.language == language.value,
                DocumentTemplateVersion.id != existing.id,
            ).update(
                {"is_published": False, "published_by_id": None, "published_at": None},
                synchronize_session=False,
            )
            existing.is_published = True
            existing.published_by_id = admin.id
            existing.published_at = existing.published_at or utcnow()
    db.commit()

def seed_database(db: Session) -> None:
    _seed_verified_registry(db)
    _seed_documents_and_catalog(db)
    _seed_document_templates(db)
