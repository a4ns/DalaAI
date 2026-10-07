"""Trusted current private-blob integrity at human CLOSE, under existing DB locks."""
from dataclasses import replace
from app.orders.models import DomainError
from app.persistence.postgres import PostgresReferences
from app.photos.validation import PhotoUnavailable


class VerifiedPhotoReferences(PostgresReferences):
    def __init__(self, repository, principal, real_now, order, *, verifier):
        super().__init__(repository,principal,real_now,order)
        self.verifier=verifier

    def closure_evidence(self, submission):
        codes, materials, photos = super().closure_evidence(submission)
        verified=[]
        for photo in photos:
            valid=photo.file_valid
            bound=(photo.order_id==self.order.id and photo.submission_id==submission.id
                   and photo.assignment_revision==self.order.assignment_revision
                   and photo.purpose=='after')
            if valid is True and bound:
                # super() already holds SHARE locks on these same rows. The
                # store read is bounded/local and cannot modify database flags.
                row=self.db.execute('SELECT * FROM photos WHERE id=%s',(photo.id,)).fetchone()
                try:
                    valid=self.verifier(row) is True if row is not None else False
                except PhotoUnavailable:
                    raise DomainError('TEMPORARILY_UNAVAILABLE','Evidence storage is temporarily unavailable') from None
            elif not bound:
                valid=False
            verified.append(replace(photo,file_valid=valid))
        return codes,materials,tuple(verified)
