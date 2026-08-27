from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_safe_cancellation_ui_is_wired_to_batch_endpoint():
    feature = ROOT / "frontend/src/features/transfers"
    cancellation = (feature / "CancelBatchModal.tsx").read_text(encoding="utf-8")
    api = (feature / "transferApi.ts").read_text(encoding="utf-8")
    history = (feature / "BatchHistory.tsx").read_text(encoding="utf-8")
    workspace = (feature / "BulkTransfers.tsx").read_text(encoding="utf-8")
    compatibility = (ROOT / "frontend/src/BulkTransfers.tsx").read_text(encoding="utf-8")
    assert "export function CancelBatchModal" in cancellation
    assert "const trimmedReason = reason.trim()" in cancellation
    assert "transferApi.cancel(batch.batch_id, trimmedReason)" in cancellation
    assert "`/transfer-batches/${batchId}/cancel`" in api
    assert "JSON.stringify({ reason })" in api
    assert "batch.awaiting_signature_machines > 0" in history
    assert "hasPermission('transfers.create')" in workspace
    assert "export { CancelBatchModal } from './features/transfers/CancelBatchModal'" in compatibility


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
