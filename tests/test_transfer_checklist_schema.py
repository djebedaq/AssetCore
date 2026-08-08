from backend.app.schemas import BulkIssueRequest, TransferChecklistItem, TransferPartyInput


def test_checklist_accepts_lengths_and_conditions():
    item = TransferChecklistItem(code="hp_hose", label="Шланг изходящ ВН", condition="GOOD", length_m=25.5)
    assert item.length_m == 25.5

def test_bulk_issue_contains_checklist():
    request = BulkIssueRequest(machine_ids=[1], location_id=1, usage_text="Проверено предназначение", condition_text="Изправна", recipient=TransferPartyInput(first_name="Иван", middle_name="Петров", last_name="Иванов"), checklist=[{"code":"pump","label":"Помпа","condition":"GOOD"}])
    assert request.checklist[0].code == "pump"
