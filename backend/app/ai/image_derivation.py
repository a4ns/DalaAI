"""Bounded local derivation from already integrity-verified private source bytes.

Metadata stripping is NOT pixel anonymization or proof of repair quality.
Derivatives are kept in memory and need exact synthetic-payload approval before
any external request. No file/network/storage/credential operation occurs here.
"""
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import re
from threading import BoundedSemaphore
import warnings

from .models import InputValidationError

DERIVATION_VERSION='model-png-rgb-1'
MAX_SOURCE_BYTES=8*1024*1024
MAX_SOURCE_PIXELS=20_000_000
MAX_MODEL_BYTES=1024*1024
MODEL_EDGES=(1280,1024,768,512)
_FORMATS={'JPEG':'image/jpeg','PNG':'image/png','WEBP':'image/webp'}
_DECODE_SLOT=BoundedSemaphore(1)


@dataclass(frozen=True,slots=True)
class ImageDerivation:
    photo_id:str
    source_sha256:str
    source_mime:str
    source_bytes:int
    source_width:int
    source_height:int
    derived_sha256:str
    derived_bytes:int
    derived_width:int
    derived_height:int
    version:str=DERIVATION_VERSION

    def __post_init__(self):
        from .rules import _uuid
        _uuid(self.photo_id,'derivation_photo_id')
        if (not re.fullmatch('[a-f0-9]{64}',self.source_sha256)
                or not re.fullmatch('[a-f0-9]{64}',self.derived_sha256)
                or self.source_mime not in _FORMATS.values()
                or any(type(x) is not int or x<1 for x in (self.source_bytes,self.source_width,
                    self.source_height,self.derived_bytes,self.derived_width,self.derived_height))
                or self.source_bytes>MAX_SOURCE_BYTES or self.source_width*self.source_height>MAX_SOURCE_PIXELS
                or self.derived_bytes>MAX_MODEL_BYTES or max(self.derived_width,self.derived_height)>1280
                or self.version!=DERIVATION_VERSION):
            raise InputValidationError('IMAGE_DERIVATION_PROVENANCE_INVALID')

    def to_audit(self):
        from dataclasses import asdict
        return asdict(self)


class _BoundedPng(BytesIO):
    def write(self,data):
        if self.tell()+len(data)>MAX_MODEL_BYTES:
            raise _OutputTooLarge()
        return super().write(data)


class _OutputTooLarge(Exception):pass


def derive_model_png(raw,*,photo_id,source_mime,source_sha256):
    """Returns (metadata-free PNG bytes, exact source/derived audit binding).

    The caller must first use PhotoIntegrityVerifier.read(row), not read any path
    supplied by a user. This function independently verifies the expected digest,
    actual MIME, full bounded decode and one-frame policy. Unknown content fails
    closed. Caller may use honest rules fallback when this raises a safe code.
    """
    if (type(raw) is not bytes or not 0<len(raw)<=MAX_SOURCE_BYTES
            or source_mime not in _FORMATS.values() or type(source_sha256) is not str
            or not re.fullmatch('[a-f0-9]{64}',source_sha256)
            or sha256(raw).hexdigest()!=source_sha256):
        raise InputValidationError('MODEL_SOURCE_INTEGRITY_INVALID')
    if not _DECODE_SLOT.acquire(blocking=False):
        raise InputValidationError('MODEL_IMAGE_DERIVATION_BUSY')
    try:
        from PIL import Image,ImageOps,UnidentifiedImageError
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw),formats=list(_FORMATS)) as probe:
                width,height=probe.size;fmt=probe.format
                if (width<1 or height<1 or width*height>MAX_SOURCE_PIXELS
                        or getattr(probe,'n_frames',1)!=1 or _FORMATS.get(fmt)!=source_mime):
                    raise InputValidationError('MODEL_SOURCE_FORMAT_OR_DIMENSION_INVALID')
                probe.verify()
            with Image.open(BytesIO(raw),formats=list(_FORMATS)) as source:
                source.load()
                ImageOps.exif_transpose(source,in_place=True)
                # RGBA input is composited onto white; invisible RGB data is not
                # exposed by blindly dropping alpha. New raster has no metadata.
                if 'A' in source.getbands() or 'transparency' in source.info:
                    rgba=source.convert('RGBA')
                    clean=Image.new('RGB',rgba.size,'white')
                    alpha=rgba.getchannel('A')
                    clean.paste(rgba,mask=alpha)
                    alpha.close();rgba.close()
                else:
                    converted=source.convert('RGB')
                    clean=Image.new('RGB',converted.size)
                    clean.paste(converted)
                    converted.close()
                source.close()
                try:
                    for edge in MODEL_EDGES:
                        resized=clean.copy()
                        try:
                            resized.thumbnail((edge,edge),resample=Image.Resampling.LANCZOS,reducing_gap=3.0)
                            output=_BoundedPng()
                            try:
                                resized.save(output,format='PNG',compress_level=6)
                                result=output.getvalue()
                            except _OutputTooLarge:
                                continue
                            proof=ImageDerivation(photo_id,source_sha256,source_mime,len(raw),width,height,
                                sha256(result).hexdigest(),len(result),resized.width,resized.height)
                            return result,proof
                        finally:resized.close()
                finally:clean.close()
        raise InputValidationError('MODEL_DERIVATION_OUTPUT_TOO_LARGE')
    except InputValidationError:
        raise
    except Exception:
        # Decoder/library exception text may include supplied metadata. Never
        # expose it; missing decoder support is an honest local fallback reason.
        raise InputValidationError('MODEL_SOURCE_DECODE_UNAVAILABLE') from None
    finally:_DECODE_SLOT.release()
