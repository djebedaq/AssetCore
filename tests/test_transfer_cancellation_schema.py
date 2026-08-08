import pytest
from app.models import TransferBatchStatus
from app.schemas import CancelTransferBatchRequest
from pydantic import ValidationError


def test_cancel_reason_is_required():
    request = CancelTransferBatchRequest(reason="Подписването е отказано")
    assert request.reason == "Подписването е отказано"


def test_cancelled_batch_status_exists():
    assert TransferBatchStatus.CANCELLED.value == "CANCELLED"


def test_cancel_reason_is_trimmed_and_blank_reason_is_rejected():
    request = CancelTransferBatchRequest(reason="  Получателят отказа  ")
    assert request.reason == "Получателят отказа"
    with pytest.raises(ValidationError):
        CancelTransferBatchRequest(reason="   ")
