# Scoped decisions for proposal.2

Overall contract remains PROPOSED; B0/C0 consumer approval pending. No SQL applied.

## New-issue future deadline

A0 accepted the product rule in coordination on 2026-10-07: a newly issued order must have due_at > domain_now when processed. This is a team choice, not an official case fact. Preserve historical seed records and dates. If network delay makes a draft deadline expire, return a clear validation error without changing it automatically.

## Staged-photo section binding

A0 directed strong binding after independent A1/A2 review found an interface gap: A2 requires trusted section_id but the old staging request/response/DB candidate did not carry it for before-photos.

Proposal: required StagePhotoRequest.section_id, persisted non-null photos.section_id, returned StagedPhoto.section_id; validate master scope for before and DB-loaded order section plus assignment for after. Pass destination_section_id through the A1 photo-validation port so attachment checks owner, section equality, TTL and applicable order/revision. An attached-photo composite foreign key binds its section to its order. No extra equipment field is needed: create already verifies equipment belongs to the selected destination section.

Missing/ill-typed section -> 422 VALIDATION_FAILED. Valid but wrong section -> 403 FORBIDDEN with no foreign photo contents. The negative wrong-section fixture uses a master authorized in both sections to prove the destination-binding rule, not just a missing permission. It is a semantic scenario and requires actual adapter execution; schema validation alone cannot prove it.

A1/A2 review and A0 approval of exact proposal.2 bytes remain pending at packaging. A5 must replace the review-only pack and rerun aggregate/CI only after A0 authorizes the update. No accepted contract migration or production schema change is implied.
