"""Integration seams; no database, network, auth implementation or atomicity claim."""
from typing import Protocol

from .models import Actor, Assignment, MutationPlan, Order, Submission


class References(Protocol):
    """Trusted server-side lookups, never flags taken from the request body.

    The adapter must revalidate staged ownership/section/TTL and reserve attachment in
    the same transaction that commits the plan. False/unknown denies use.
    """
    def equipment_in_section(self, equipment_id: str, section_id: str) -> bool: ...
    def assignment_in_section(self, assignment: Assignment, section_id: str) -> bool: ...
    def work_code_exists(self, work_code_id: str) -> bool: ...
    def material_exists(self, material_id: str) -> bool: ...
    def staged_photo_usable(self, photo_id: str, purpose: str, actor_id: str,
                            destination_section_id: str, order_id: str | None, assignment_revision: int | None) -> bool: ...


class SessionAuthority(Protocol):
    def authenticate(self, session_token: str) -> Actor: ...
    def authorize_current_object(self, actor: Actor, order: Order) -> None: ...


class OrderRepository(Protocol):
    def load_order(self, order_id: str) -> Order | None: ...
    def load_submission(self, submission_id: str) -> Submission | None: ...
    def commit_new_operation(self, plan: MutationPlan, actor_id: str,
                             operation_id: str, canonical_request_hash: str) -> object:
        """Commit CAS + events + attachments + jobs + receipt atomically.

        This signature is intentionally not implemented. Current authorization
        and receipt lookup MUST precede prepare_new_command. Receipt uniqueness
        is actor+operation_id. Same hash replay returns original committed result.
        On a CAS loser, roll back then re-read the committed receipt before 409;
        changed hash is OPERATION_ID_REUSED. Allocate per-order event sequence and
        real recorded_at here. A pure domain version check is NOT DB atomicity.
        """
        ...
