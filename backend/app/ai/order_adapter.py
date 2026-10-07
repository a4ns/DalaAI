"""Thin A1 snapshot mapping. No repository dependency or persistence operations."""
from typing import TYPE_CHECKING

from .models import ClosureInput, EvidenceContext, InputValidationError, Material, PhotoEvidence

if TYPE_CHECKING:
    from app.orders.models import Order, Submission


def from_order_snapshot(order: 'Order', submission: 'Submission', *,
                        work_code_ids: frozenset[str] | None,
                        material_ids: frozenset[str] | None,
                        photos: tuple[PhotoEvidence, ...]) -> tuple[ClosureInput, EvidenceContext]:
    """Caller authenticates/authorizes, loads immutable data, then rechecks under lock.

    CURRENT_ATTEMPT matches A1 assessment_is_current. A stale result may be
    archived on its old attempt, but cannot affect current state/version/jobs.
    A6 persistence and close adapter must call gates again using trusted evidence.
    """
    if submission.order_id != order.id:
        raise InputValidationError('SUBMISSION_ORDER_MISMATCH')
    payload = submission.payload
    data = ClosureInput(submission.order_id, submission.id, submission.assignment_revision,
                        str(order.type), order.description, payload.work_description,
                        payload.work_code_id, tuple(Material(m.material_id, m.quantity) for m in payload.materials),
                        payload.after_photo_ids)
    context = EvidenceContext(order.id, order.current_submission_id, order.assignment_revision,
                              str(order.status), None if submission.completeness is None else str(submission.completeness),
                              tuple(str(item) for item in submission.missing_evidence),
                              work_code_ids, material_ids, photos)
    return data, context
