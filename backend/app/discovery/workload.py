"""Explicit candidate dictionary semantics; a representative is not exclusivity."""
from dataclasses import dataclass

ACTIVE_STATUSES = frozenset({"in_progress", "paused"})
QUEUE_STATUSES = frozenset({"queued"})
POLICY_NAME = "representative_lowest_number_explicit_queue_v1"


@dataclass(frozen=True)
class WorkloadPolicy:
    """Caller must acknowledge this named policy; alternatives need a new decision.

    Counts and representatives cover only caller-visible current assignments.
    Accepted/issued/rework are not the explicit queued state. More than one active
    assignment is legal; choose its lowest numeric number without implying only one.
    """
    name: str

    def __post_init__(self):
        if self.name != POLICY_NAME:
            raise ValueError("Unsupported dictionary workload policy; require an explicit contract decision")

    def summarize(self, rows):
        active=[row for row in rows if row["status"] in ACTIVE_STATUSES]
        active.sort(key=lambda row:int(row["number"]))
        return {"active_order_id":str(active[0]["id"]) if active else None,
                "queue_count":sum(row["status"] in QUEUE_STATUSES for row in rows)}
