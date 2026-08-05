from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_safe_cancellation_ui_is_wired_to_batch_endpoint():
    source = (ROOT / "frontend/src/BulkTransfers.tsx").read_text(encoding="utf-8")
    assert "export function CancelBatchModal" in source
    assert "`/transfer-batches/${batch.batch_id}/cancel`" in source
    assert "JSON.stringify({ reason: trimmedReason })" in source
    assert "batch.awaiting_signature_machines > 0" in source
    assert "hasPermission('transfers.create')" in source


def test_safe_cancellation_ui_has_localized_effect_messages():
    translations = (ROOT / "frontend/src/i18n.tsx").read_text(encoding="utf-8")
    for key in (
        "bulk.cancelPendingAction",
        "bulk.cancelIssueEffect",
        "bulk.cancelReturnEffect",
        "bulk.cancelReasonRequired",
        "errors.batchNotPending",
    ):
        assert translations.count(f"'{key}'") >= 3


def test_transfer_buttons_do_not_show_group_wording():
    translations = (ROOT / "frontend/src/i18n.tsx").read_text(encoding="utf-8")
    assert "'bulk.issue': 'Издай'" in translations
    assert "'bulk.return': 'Приеми'" in translations
    assert "Потвърждение на груповото издаване" not in translations
