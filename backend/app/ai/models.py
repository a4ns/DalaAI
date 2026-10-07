"""Internal assessment values. Never deserialize trusted evidence from an HTTP body."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

GateStatus = Literal['pass', 'fail', 'unknown']


@dataclass(frozen=True, slots=True)
class Material:
    material_id: str
    quantity: Decimal


@dataclass(frozen=True, slots=True)
class ClosureInput:
    order_id: str
    submission_id: str
    assignment_revision: int
    order_type: Literal['planned', 'unplanned']
    problem_description: str
    work_description: str
    work_code_id: str | None
    materials: tuple[Material, ...]
    after_photo_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PhotoEvidence:
    id: str
    order_id: str
    submission_id: str
    assignment_revision: int
    purpose: Literal['before', 'after']
    file_valid: bool | None


@dataclass(frozen=True, slots=True)
class EvidenceContext:
    """Server-loaded current snapshot and evidence; None always means unknown.

    file_valid means decoded, sanitized upload validation, NOT repair quality.
    Caller must load bound photos and current references under the close lock.
    """
    current_order_id: str
    current_submission_id: str | None
    current_assignment_revision: int
    current_status: str
    submission_completeness: Literal['complete', 'incomplete'] | None
    missing_evidence: tuple[str, ...]
    work_code_ids: frozenset[str] | None
    material_ids: frozenset[str] | None
    photos: tuple[PhotoEvidence, ...]


@dataclass(frozen=True, slots=True)
class Gate:
    code: str
    status: GateStatus
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GateReport:
    gates: tuple[Gate, ...]
    stale: bool

    @property
    def closure_permitted(self) -> bool:
        """Mandatory gates only. This is NEVER a production acceptance decision."""
        return bool(self.gates) and all(g.status == 'pass' for g in self.gates)

    @property
    def counts(self) -> dict[str, int]:
        return {status: sum(g.status == status for g in self.gates)
                for status in ('pass', 'fail', 'unknown')}


@dataclass(frozen=True, slots=True)
class Assessment:
    id: str
    submission_id: str
    assignment_revision: int
    duration_ms: int
    recommendation: Literal['rework_recommended', 'needs_master_review']
    reasons: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    fallback_reason: str
    stale: bool
    created_at: datetime

    def to_wire(self) -> dict[str, object]:
        """Exactly A6 Assessment schema v1. No model/quality score is fabricated."""
        return {
            'id': self.id, 'submission_id': self.submission_id,
            'assignment_revision': self.assignment_revision, 'schema_version': '1',
            'mode': 'rules_fallback', 'model': None, 'model_version': None,
            'duration_ms': self.duration_ms, 'recommendation': self.recommendation,
            'score': None, 'reasons': list(self.reasons),
            'evidence_ids': list(self.evidence_ids), 'fallback_reason': self.fallback_reason,
            'stale': self.stale, 'created_at': self.created_at.isoformat().replace('+00:00', 'Z'),
        }


class InputValidationError(ValueError):
    """Code/path only: do not include raw text, IDs or exception messages in logs."""
