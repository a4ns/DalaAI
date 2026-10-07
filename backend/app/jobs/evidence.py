"""Conservative default until a trusted private-blob verifier is configured."""
from dataclasses import replace

from app.persistence.postgres import PostgresReferences


class UnverifiedPhysicalReferences(PostgresReferences):
    def closure_evidence(self, submission):
        codes, materials, photos = super().closure_evidence(submission)
        # Stored true only proves a past validation. Without consulting private
        # bytes we cannot establish their present availability/integrity. Keep
        # known invalid evidence false; don't convert missing evidence to valid.
        return codes, materials, tuple(
            replace(photo, file_valid=None) if photo.file_valid is True else photo
            for photo in photos)
