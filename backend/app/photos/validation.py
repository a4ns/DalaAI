"""Validate actual bytes, then persist only a fresh metadata-free raster.

File validity means decodable bounded raster, never authenticity of a repair,
capture time, place, subject or photographer. EXIF and MIME are untrusted input.
"""
from dataclasses import asdict, dataclass
from hashlib import sha256
from io import BytesIO
import re
from threading import BoundedSemaphore
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

from app.orders.models import DomainError
from app.orders.validation import uid
from app.persistence.canonical import canonical_json

MAX_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 20_000_000
_DECODE_SLOTS = BoundedSemaphore(1)
_MIME = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


class _BoundedOutput(BytesIO):
    def write(self, data):
        if self.tell() + len(data) > MAX_BYTES:
            raise DomainError("PAYLOAD_TOO_LARGE", "Sanitized photo exceeds the byte limit")
        return super().write(data)


class PhotoUnavailable(Exception):
    """Safe generic 503: no confirmed result, retry the same operation."""


@dataclass(frozen=True)
class StageRequest:
    operation_id: str
    section_id: str
    purpose: str
    expected_version: int = 0
    order_id: str | None = None
    assignment_revision: int | None = None


@dataclass(frozen=True)
class ValidatedRaster:
    data: bytes
    mime_type: str
    sha256: str
    width: int
    height: int


def parse_fields(fields):
    required = {"operation_id", "section_id", "purpose", "expected_version"}
    optional = {"order_id", "assignment_revision"}
    if (type(fields) is not dict or not required <= fields.keys()
            or fields.keys() - required - optional
            or any(type(v) is not str or len(v) > 128 or "\x00" in v for v in fields.values())):
        raise DomainError("VALIDATION_FAILED", "Invalid photo form fields")
    if fields["expected_version"] != "0" or fields["purpose"] not in {"before", "after"}:
        raise DomainError("VALIDATION_FAILED", "Invalid photo purpose or version")
    after = fields["purpose"] == "after"
    if (after and fields.keys() != required | optional) or (not after and fields.keys() != required):
        raise DomainError("VALIDATION_FAILED", "Photo purpose has incompatible binding fields")
    revision = None
    if after:
        text = fields["assignment_revision"]
        if not re.fullmatch(r"[1-9][0-9]{0,9}", text) or int(text) > 2147483647:
            raise DomainError("VALIDATION_FAILED", "Invalid assignment revision")
        revision = int(text)
    return StageRequest(uid(fields["operation_id"], "operation_id"),
        uid(fields["section_id"], "section_id"), fields["purpose"],
        order_id=uid(fields["order_id"], "order_id") if after else None,
        assignment_revision=revision)


def request_hash(request, raw):
    if type(raw) is not bytes or not raw:
        raise DomainError("UNSUPPORTED_MEDIA_TYPE", "A nonempty image is required")
    if len(raw) > MAX_BYTES:
        raise DomainError("PAYLOAD_TOO_LARGE", "Photo exceeds the byte limit")
    return sha256(canonical_json({"canonical_version": 1, "method": "POST",
        "route": "/api/v1/photos/stage", "form": asdict(request),
        "raw_file_sha256": sha256(raw).hexdigest()}).encode("utf-8")).hexdigest()


def decode_raster(raw, declared_mime=None):
    """No client can set file_valid. Native decoder is bounded and fail-closed."""
    if type(raw) is not bytes or not raw:
        raise DomainError("UNSUPPORTED_MEDIA_TYPE", "A nonempty image is required")
    if len(raw) > MAX_BYTES:
        raise DomainError("PAYLOAD_TOO_LARGE", "Photo exceeds the byte limit")
    if not _DECODE_SLOTS.acquire(blocking=False):
        raise PhotoUnavailable()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw), formats=list(_MIME)) as probe:
                fmt = probe.format
                width, height = probe.size
                if width < 1 or height < 1 or width * height > MAX_PIXELS:
                    raise DomainError("PAYLOAD_TOO_LARGE", "Photo exceeds the pixel limit")
                if getattr(probe, "n_frames", 1) != 1:
                    raise DomainError("UNSUPPORTED_MEDIA_TYPE", "Only single-frame images are supported")
                if declared_mime not in (None, "application/octet-stream", _MIME[fmt]):
                    raise DomainError("UNSUPPORTED_MEDIA_TYPE", "Image type does not match the file")
                probe.verify()
            with Image.open(BytesIO(raw), formats=list(_MIME)) as source:
                source.load()  # Full decode, never trust header dimensions alone.
                ImageOps.exif_transpose(source, in_place=True)
                mode = "RGB" if fmt == "JPEG" else "RGBA"
                converted = source.convert(mode)
                # New raster + pixel paste copies no info/EXIF/XMP/ICC/text.
                # Avoid an extra full-raster tobytes() allocation at 20 MP.
                clean = Image.new(mode, converted.size)
                clean.paste(converted)
                # Re-encoders may need substantial native scratch space. Release
                # both input rasters before invoking them, keeping only clean.
                converted.close()
                source.close()
                try:
                    output = _BoundedOutput()
                    options = {"quality": 90} if fmt == "JPEG" else {"lossless": True} if fmt == "WEBP" else {}
                    clean.save(output, format=fmt, **options)
                    data = output.getvalue()
                    width, height = clean.size
                finally:
                    clean.close()
        if not 0 < len(data) <= MAX_BYTES:
            raise DomainError("PAYLOAD_TOO_LARGE", "Sanitized photo exceeds the byte limit")
        return ValidatedRaster(data, _MIME[fmt], sha256(data).hexdigest(), width, height)
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise DomainError("UNSUPPORTED_MEDIA_TYPE", "Unsupported or invalid image") from None
    finally:
        _DECODE_SLOTS.release()
