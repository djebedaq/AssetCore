from __future__ import annotations
from datetime import datetime
from enum import Enum
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

class MachineStatus(str, Enum):
    READY='Готова'; ISSUED='Издадена'; IN_USE='В употреба'; RETURNED='Върната'; INSPECTION='За преглед'; CLEANING='Почистване'; REPAIR='В ремонт'; WAITING_APPROVAL='Чака одобрение'; WAITING_PARTS='Чака части'; TESTING='Тестване'

class User(Base):
    __tablename__='users'
    id: Mapped[int]=mapped_column(primary_key=True)
    email: Mapped[str]=mapped_column(String(255),unique=True,index=True)
    full_name: Mapped[str]=mapped_column(String(255),default='Администратор')
    password_hash: Mapped[str]=mapped_column(String(255))
    role: Mapped[str]=mapped_column(String(50),default='admin')
    is_active: Mapped[bool]=mapped_column(default=True)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)

class Location(Base):
    __tablename__='locations'
    id: Mapped[int]=mapped_column(primary_key=True)
    name: Mapped[str]=mapped_column(String(120),unique=True,index=True)
    description: Mapped[str|None]=mapped_column(Text,nullable=True)

class Machine(Base):
    __tablename__='machines'
    id: Mapped[int]=mapped_column(primary_key=True)
    inventory_number: Mapped[str]=mapped_column(String(50),unique=True,index=True)
    name: Mapped[str]=mapped_column(String(255))
    category: Mapped[str]=mapped_column(String(120),default='HPWJ')
    brand: Mapped[str]=mapped_column(String(120))
    model: Mapped[str|None]=mapped_column(String(120),nullable=True)
    pressure_bar: Mapped[int]=mapped_column(Integer,default=500)
    serial_number: Mapped[str|None]=mapped_column(String(120),nullable=True)
    status: Mapped[str]=mapped_column(String(80),default=MachineStatus.READY.value)
    location_id: Mapped[int|None]=mapped_column(ForeignKey('locations.id'),nullable=True)
    notes: Mapped[str|None]=mapped_column(Text,nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
    updated_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow,onupdate=datetime.utcnow)
    location: Mapped[Location|None]=relationship()
    repairs: Mapped[list['Repair']]=relationship(back_populates='machine',cascade='all, delete-orphan')
    transfers: Mapped[list['TransferProtocol']]=relationship(back_populates='machine',cascade='all, delete-orphan')

class Repair(Base):
    __tablename__='repairs'
    id: Mapped[int]=mapped_column(primary_key=True)
    machine_id: Mapped[int]=mapped_column(ForeignKey('machines.id'),index=True)
    reported_problem: Mapped[str]=mapped_column(Text)
    diagnosis: Mapped[str|None]=mapped_column(Text,nullable=True)
    work_performed: Mapped[str|None]=mapped_column(Text,nullable=True)
    result: Mapped[str|None]=mapped_column(Text,nullable=True)
    status: Mapped[str]=mapped_column(String(80),default='Приета')
    opened_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
    closed_at: Mapped[datetime|None]=mapped_column(DateTime,nullable=True)
    machine: Mapped[Machine]=relationship(back_populates='repairs')

class TransferProtocol(Base):
    __tablename__='transfer_protocols'
    id: Mapped[int]=mapped_column(primary_key=True)
    machine_id: Mapped[int]=mapped_column(ForeignKey('machines.id'),index=True)
    protocol_type: Mapped[str]=mapped_column(String(40),default='Предаване')
    protocol_number: Mapped[str]=mapped_column(String(80),unique=True,index=True)
    company_unit: Mapped[str|None]=mapped_column(String(255),nullable=True)
    vessel: Mapped[str|None]=mapped_column(String(255),nullable=True)
    location_text: Mapped[str|None]=mapped_column(String(255),nullable=True)
    handed_over_by: Mapped[str|None]=mapped_column(String(255),nullable=True)
    accepted_by: Mapped[str|None]=mapped_column(String(255),nullable=True)
    equipment: Mapped[str|None]=mapped_column(Text,nullable=True)
    condition_text: Mapped[str|None]=mapped_column(Text,nullable=True)
    remarks: Mapped[str|None]=mapped_column(Text,nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
    machine: Mapped[Machine]=relationship(back_populates='transfers')

class PartRequest(Base):
    __tablename__='part_requests'
    id: Mapped[int]=mapped_column(primary_key=True)
    machine_id: Mapped[int|None]=mapped_column(ForeignKey('machines.id'),nullable=True)
    part_name: Mapped[str]=mapped_column(String(255))
    part_number: Mapped[str|None]=mapped_column(String(120),nullable=True)
    quantity: Mapped[int]=mapped_column(Integer,default=1)
    reason: Mapped[str|None]=mapped_column(Text,nullable=True)
    priority: Mapped[str]=mapped_column(String(50),default='Нормален')
    status: Mapped[str]=mapped_column(String(80),default='Чернова')
    created_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
    machine: Mapped[Machine|None]=relationship()

class PartCatalog(Base):
    __tablename__='part_catalog'
    id: Mapped[int]=mapped_column(primary_key=True)
    brand: Mapped[str]=mapped_column(String(120),index=True)
    model: Mapped[str|None]=mapped_column(String(120),nullable=True)
    assembly: Mapped[str|None]=mapped_column(String(255),nullable=True)
    position: Mapped[str|None]=mapped_column(String(40),nullable=True)
    part_number: Mapped[str]=mapped_column(String(120),index=True)
    description: Mapped[str]=mapped_column(String(500))
    quantity: Mapped[int|None]=mapped_column(Integer,nullable=True)
    source_document: Mapped[str|None]=mapped_column(String(500),nullable=True)
    source_page: Mapped[int|None]=mapped_column(Integer,nullable=True)

class TechnicalDocument(Base):
    __tablename__='technical_documents'
    id: Mapped[int]=mapped_column(primary_key=True)
    brand: Mapped[str]=mapped_column(String(120),index=True)
    category: Mapped[str]=mapped_column(String(120))
    title: Mapped[str]=mapped_column(String(500))
    file_path: Mapped[str]=mapped_column(String(700),unique=True)

class AuditLog(Base):
    __tablename__='audit_logs'
    id: Mapped[int]=mapped_column(primary_key=True)
    entity_type: Mapped[str]=mapped_column(String(80),index=True)
    entity_id: Mapped[int|None]=mapped_column(Integer,nullable=True)
    action: Mapped[str]=mapped_column(String(120))
    details: Mapped[str|None]=mapped_column(Text,nullable=True)
    user_name: Mapped[str|None]=mapped_column(String(255),nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow,index=True)
