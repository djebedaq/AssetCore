"""Presentation and SQL ordering use the same metric-specific date contract.

Decision dates mean the latest matching decision within the selected period.
Current states share the actual read snapshot, with the entity ID breaking ties.
"""

DETAIL_DATE_FIELDS = {
    "machines": dict.fromkeys(("total_machines", "READY", "ISSUED", "REPAIR"), "as_of"),
    "usage": {
        "issues": "issued_at",
        "unique_issued": "last_issued_at",
        "completed_cycles": "returned_at",
        "still_issued": "as_of",
        "active_issues": "as_of",
        "issue_hours": "issued_at",
        **dict.fromkeys(
            (
                "returned_ready",
                "returned_repair",
                "returned_damage",
                "returned_missing",
                "attention_returns",
            ),
            "returned_at",
        ),
    },
    "repairs": {
        "opened": "opened_at",
        "closed": "closed_at",
        "current_repairs": "as_of",
        "attention": "opened_at",
    },
    "requests": {
        "created": "created_at",
        "submitted": "submitted_at",
        "ordered": "ordered_at",
        "approved": "approved_at",
        "rejected": "rejected_at",
        "cancelled": "cancelled_at",
        "delivered": "delivered_at",
        "partial": "created_at",
        **dict.fromkeys(("pending_requests", "outstanding", "waiting_order", "delayed"), "as_of"),
        "receipts": "occurred_at",
    },
}
