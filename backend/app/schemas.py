from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, ConfigDict

class LoginRequest(BaseModel): email:str; password:str
class TokenResponse(BaseModel): access_token:str; token_type:str='bearer'; user:dict
class LocationOut(BaseModel): model_config=ConfigDict(from_attributes=True); id:int; name:str
class MachineBase(BaseModel):
    inventory_number:str; name:str; category:str='HPWJ'; brand:str; model:str|None=None; pressure_bar:int=500; serial_number:str|None=None; status:str='Готова'; location_id:int|None=None; notes:str|None=None
class MachineCreate(MachineBase): pass
class MachineUpdate(BaseModel):
    name:str|None=None; brand:str|None=None; model:str|None=None; pressure_bar:int|None=None; serial_number:str|None=None; status:str|None=None; location_id:int|None=None; notes:str|None=None
class MachineOut(MachineBase):
    model_config=ConfigDict(from_attributes=True); id:int; location:LocationOut|None=None; created_at:datetime; updated_at:datetime
class RepairCreate(BaseModel): machine_id:int; reported_problem:str; diagnosis:str|None=None; work_performed:str|None=None; result:str|None=None; status:str='Приета'
class RepairUpdate(BaseModel): diagnosis:str|None=None; work_performed:str|None=None; result:str|None=None; status:str|None=None; close:bool=False
class RepairOut(BaseModel):
    model_config=ConfigDict(from_attributes=True); id:int; machine:MachineOut; reported_problem:str; diagnosis:str|None=None; work_performed:str|None=None; result:str|None=None; status:str; opened_at:datetime; closed_at:datetime|None=None
class PartRequestCreate(BaseModel): machine_id:int|None=None; part_name:str; part_number:str|None=None; quantity:int=1; reason:str|None=None; priority:str='Нормален'; status:str='Чернова'
class PartRequestOut(PartRequestCreate):
    model_config=ConfigDict(from_attributes=True); id:int; machine:MachineOut|None=None; created_at:datetime
class TransferCreate(BaseModel):
    machine_id:int; protocol_type:str='Предаване'; company_unit:str|None=None; vessel:str|None=None; location_text:str|None=None; handed_over_by:str|None=None; accepted_by:str|None=None; equipment:str|None=None; condition_text:str|None=None; remarks:str|None=None
class TransferOut(TransferCreate):
    model_config=ConfigDict(from_attributes=True); id:int; protocol_number:str; created_at:datetime; machine:MachineOut
class PartCatalogOut(BaseModel):
    model_config=ConfigDict(from_attributes=True); id:int; brand:str; model:str|None=None; assembly:str|None=None; position:str|None=None; part_number:str; description:str; quantity:int|None=None; source_document:str|None=None; source_page:int|None=None
class TechnicalDocumentOut(BaseModel):
    model_config=ConfigDict(from_attributes=True); id:int; brand:str; category:str; title:str; file_path:str
