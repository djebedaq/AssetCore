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
    PartCatalog,
    TechnicalDocument,
    TechnicalDocumentRevision,
    User,
    UserRole,
    utcnow,
)
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
    if not settings.assetcore_owner_email or not settings.assetcore_owner_email.strip():
        raise RuntimeError(
            "ASSETCORE_OWNER_EMAIL е задължителна настройка за стартиране на AssetCore."
        )
    owner_email = settings.assetcore_owner_email.strip().casefold()
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
    if not users:
        owner = User(
            email=owner_email,
            full_name="Администратор",
            password_hash=hash_password(settings.admin_password),
            role=UserRole.ADMINISTRATOR.value,
            is_active=True,
            is_system_owner=True,
            must_change_password=False,
        )
        db.add(owner)
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

    existing_locations = {x.name: x for x in db.scalars(select(Location)).all()}
    for name in LOCATIONS:
        if name not in existing_locations:
            db.add(Location(name=name))
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
            brand = {'falch500':'Falch 500 bar','falch1000':'Falch 1000 bar','hydwin':'HYDWIN (Fussen)','combijet':'CombiJet','protocols_hpwj':'HPWJ протоколи','parts_requests_hpwj':'HPWJ заявки'}.get(brand_folder, brand_folder)
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
                db.add(TechnicalDocument(brand=brand, category=category, title=path.name, file_path=rel))
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

    verified_parts = [
        ('CombiJet','JE60-500','Chassis','1','CJL30949','Complete stainless-steel frame',1,'combijet/JE60-500_manual.pdf',28),
        ('CombiJet','JE60-500','Chassis','2','CJL30998','15 kW electric motor',1,'combijet/JE60-500_manual.pdf',28),
        ('CombiJet','JE60-500','Chassis','13','CJL30988','HP pump 500 bar',1,'combijet/JE60-500_manual.pdf',28),
        ('CombiJet','JE60-500','Chassis','14','CJL30377','Pressure regulating valve',1,'combijet/JE60-500_manual.pdf',28),
        ('CombiJet','JE60-500','Chassis','21','CJL30037','Hose 500 bar, 20 m, 1/2 fittings',1,'combijet/JE60-500_manual.pdf',28),
        ('CombiJet','JE60-500','Dry shut gun','*','CJL30904','Gun complete (positions 1-27)',1,'combijet/JE60-500_manual.pdf',44),
        ('CombiJet','JE60-500','Dry shut gun','27','CJL34153','Lance 800 mm',1,'combijet/JE60-500_manual.pdf',44),
        ('CombiJet','JE60-500','Dry shut gun','32','CJL30037','Hose 500 bar, 20 m, 1/2 fittings',1,'combijet/JE60-500_manual.pdf',44),
        ('CombiJet','JE60-500','Pressure regulating valve fittings','1','CJL30377','Pressure regulating valve',1,'combijet/JE60-500_manual.pdf',38),
        ('CombiJet','JE60-500','Pressure regulating valve fittings','2','CJNP0800000','Nipple 1/2 inch',2,'combijet/JE60-500_manual.pdf',38),
    ]
    for brand,model,assembly,pos,pn,desc,qty,src,page in verified_parts:
        if not db.scalar(select(PartCatalog).where(PartCatalog.part_number==pn, PartCatalog.assembly==assembly, PartCatalog.position==pos)):
            db.add(PartCatalog(brand=brand,model=model,assembly=assembly,position=pos,part_number=pn,description=desc,quantity=qty,source_document=src,source_page=page))
    db.commit()

    admin = db.scalar(select(User).where(User.is_system_owner.is_(True)))
    if admin:
        for part in db.scalars(select(PartCatalog)).all():
            if part.source_document and part.source_page:
                part.is_verified = True
                part.provenance_confidence = 1.0
                part.verified_by_id = admin.id
                part.verified_at = part.verified_at or utcnow()
    db.commit()


def _seed_document_templates(db: Session) -> None:
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
            "source": "reference_photos/IMG_5812.jpeg",
            "contract": {
                "page": "A4 portrait",
                "header": "KRZ, ODESSOS SHIPREPAIR & CONVERSION, RINA/AQAP",
                "sections": ["protocol_number", "machine_identity", "ten_point_checklist", "usage", "signatures"],
                "reference_only": True,
            },
        },
        {
            "code": "HPWJ_TRANSFER_RETURN",
            "document_type": DocumentType.TRANSFER_RETURN.value,
            "name_bg": "Протокол за приемане на миеща техника след използване",
            "name_en": "High-pressure washing equipment return protocol",
            "name_ru": "Протокол возврата моечной техники после использования",
            "source": "reference_photos/IMG_5814.jpeg",
            "contract": {
                "page": "A4 portrait",
                "header": "KRZ, ODESSOS SHIPREPAIR & CONVERSION, RINA/AQAP",
                "sections": ["protocol_number", "machine_identity", "ten_point_checklist", "usage", "signatures"],
                "reference_only": True,
            },
        },
        {
            "code": "HPWJ_REPAIR_PROTOCOL",
            "document_type": DocumentType.REPAIR_PROTOCOL.value,
            "name_bg": "Протокол преди/след ремонт",
            "name_en": "Before/after repair protocol",
            "name_ru": "Протокол до/после ремонта",
            "source": "technical_docs/protocols_hpwj/10. REPORT BEFORE-AFTER REPAIR - Combijet - завършен !.docx",
            "contract": {
                "page": "Letter portrait",
                "margins_inches": {"left": 0.5, "right": 0.3, "top": 0.3, "bottom": 0.3},
                "header_images": 3,
                "sections": ["machine_identity", "condition_before", "diagnosis", "repair_actions", "parts", "test", "condition_after", "signatures"],
                "reference_only": True,
            },
        },
        {
            "code": "HPWJ_PART_REQUEST",
            "document_type": DocumentType.PART_REQUEST.value,
            "name_bg": "Техническа спецификация за доставка на резервни части",
            "name_en": "Technical specification for spare-parts supply",
            "name_ru": "Техническая спецификация на поставку запасных частей",
            "source": "technical_docs/parts_requests_hpwj/KK 1001 FALCH 500.docx",
            "contract": {
                "page": "Letter portrait",
                "margins_inches": {"left": 0.5, "right": 0.5, "top": 0.5, "bottom": 0.5},
                "header_images": 2,
                "sections": ["technical_specification_title", "machine_identity", "parts_table", "remarks", "request_reference_date_requester"],
                "reference_only": True,
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
        source = resources / definition["source"]
        digest = hashlib.sha256(source.read_bytes()).hexdigest() if source.is_file() else None
        for language in LanguageCode:
            existing = db.scalar(
                select(DocumentTemplateVersion).where(
                    DocumentTemplateVersion.template_id == template.id,
                    DocumentTemplateVersion.version == 1,
                    DocumentTemplateVersion.language == language.value,
                )
            )
            if existing is None:
                db.add(
                    DocumentTemplateVersion(
                        template_id=template.id,
                        version=1,
                        language=language.value,
                        source_path=definition["source"],
                        source_sha256=digest,
                        layout_contract=definition["contract"],
                        is_published=language == LanguageCode.BG,
                        published_by_id=(admin.id if language == LanguageCode.BG else None),
                        created_by_id=admin.id,
                        published_at=(utcnow() if language == LanguageCode.BG else None),
                    )
                )
    db.commit()

def seed_database(db: Session) -> None:
    _seed_verified_registry(db)
    _seed_documents_and_catalog(db)
    _seed_document_templates(db)
