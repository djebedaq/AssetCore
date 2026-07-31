from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Location,
    Machine,
    MachineStatus,
    PartCatalog,
    TechnicalDocument,
    User,
    UserRole,
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
    if not db.scalar(select(User).limit(1)):
        db.add(User(
            email=settings.admin_email,
            full_name="Администратор",
            password_hash=hash_password(settings.admin_password),
            role=UserRole.ADMIN.value,
        ))

    existing_locations = {x.name: x for x in db.scalars(select(Location)).all()}
    for name in LOCATIONS:
        if name not in existing_locations:
            db.add(Location(name=name))
    db.commit()

    locations = {x.name: x for x in db.scalars(select(Location)).all()}
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
        machine.brand = item["brand"]
        machine.model = item["model"]
        machine.pressure_bar = item["pressure_bar"]
        machine.serial_number = item["serial_number"]
        if machine.location_id is None:
            machine.location_id = locations["Цех"].id
    db.commit()

# --- Director Preview: technical library and verified catalog records ---
def _seed_documents_and_catalog(db: Session) -> None:
    from pathlib import Path
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

def seed_database(db: Session) -> None:
    _seed_verified_registry(db)
    _seed_documents_and_catalog(db)
