from app.models import MachineStatus
from app.schemas import BulkReturnItem, TransferChecklistItem


def test_checklist_label_is_optional_and_condition_is_validated():
    item = TransferChecklistItem(code="pump", condition="GOOD")
    assert item.code == "pump"
    assert item.label is None


def test_bulk_return_item_accepts_frontend_checklist_contract():
    item = BulkReturnItem(
        transfer_id=1,
        machine_id=1,
        condition_text="Добро",
        result_text="Приета",
        next_status=MachineStatus.INSPECTION,
        checklist=[{"code": "pump", "condition": "GOOD", "note": None, "length_m": None}],
    )
    assert item.checklist[0].code == "pump"
