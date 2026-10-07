"""Real decoder/filesystem tests; generated synthetic images only."""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from PIL import Image, PngImagePlugin

from app.orders.models import DomainError
from app.photos import validation
from app.photos.multipart import MAX_REQUEST_BYTES, UploadParser
from app.photos.storage import PrivateFileStore
from app.photos.validation import (MAX_BYTES, PhotoUnavailable, decode_raster,
                                  parse_fields, request_hash)

SECTION = "00000000-0000-4000-8000-000000000001"
OPERATION = "00000000-0000-4000-8000-000000000002"
ORDER = "00000000-0000-4000-8000-000000000003"


def fields(**updates):
    return {"section_id": SECTION, "operation_id": OPERATION, "expected_version": "0",
            "purpose": "before", **updates}


def image_bytes(fmt="PNG", **options):
    image = Image.new("RGB", (13, 17), (20, 80, 120))
    stream = BytesIO()
    image.save(stream, fmt, **options)
    image.close()
    return stream.getvalue()


def multipart(parts, boundary="bounded-test"):
    chunks = []
    for name, value, filename, mime in parts:
        headers = f'Content-Disposition: form-data; name="{name}"'
        if filename is not None:
            headers += f'; filename="{filename}"'
        if mime:
            headers += f'\r\nContent-Type: {mime}'
        chunks.append(b"--" + boundary.encode() + b"\r\n" + headers.encode() + b"\r\n\r\n"
                      + (value.encode() if isinstance(value, str) else value) + b"\r\n")
    return b"".join(chunks) + b"--" + boundary.encode() + b"--\r\n"


class ValidationTests(unittest.TestCase):
    def test_real_decode_reencode_formats_and_hash(self):
        for fmt, mime in [("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")]:
            with self.subTest(fmt=fmt):
                result = decode_raster(image_bytes(fmt), mime)
                self.assertEqual(result.mime_type, mime)
                self.assertEqual(result.sha256, sha256(result.data).hexdigest())
                self.assertEqual((result.width, result.height), (13, 17))
                with Image.open(BytesIO(result.data)) as decoded:
                    decoded.load()
                    self.assertEqual(decoded.format, fmt)
                    self.assertFalse(decoded.getexif())

    def test_metadata_removed_and_orientation_not_authenticity(self):
        exif = Image.Exif()
        exif[270] = "synthetic-private-metadata"
        exif[274] = 6
        exif[315] = "synthetic photographer"
        for fmt in ("JPEG", "PNG", "WEBP"):
            raw = image_bytes(fmt, exif=exif.tobytes())
            result = decode_raster(raw)
            self.assertNotIn(b"synthetic-private", result.data)
            self.assertEqual((result.width, result.height), (17, 13))
            with Image.open(BytesIO(result.data)) as decoded:
                self.assertFalse(decoded.getexif())
                self.assertNotIn("exif", decoded.info)
                self.assertNotIn("xmp", decoded.info)
        text = PngImagePlugin.PngInfo()
        text.add_text("Description", "synthetic-private-comment")
        clean = decode_raster(image_bytes("PNG", pnginfo=text)).data
        self.assertNotIn(b"synthetic-private", clean)

    def test_invalid_truncated_mime_and_unsupported(self):
        for raw, mime in [(b"<svg>invalid</svg>", "image/png"), (b"not-image", None),
                          (image_bytes()[:40], None), (image_bytes(), "image/jpeg"),
                          (image_bytes("GIF"), "image/gif"), (b"", None)]:
            with self.subTest(mime=mime), self.assertRaises(DomainError) as error:
                decode_raster(raw, mime)
            self.assertEqual(error.exception.code, "UNSUPPORTED_MEDIA_TYPE")

    def test_animated_png_webp_rejected(self):
        frames = [Image.new("RGB", (5, 5), color) for color in ("red", "blue")]
        for fmt in ("PNG", "WEBP"):
            stream = BytesIO()
            frames[0].save(stream, fmt, save_all=True, append_images=frames[1:], duration=50, loop=0)
            with self.assertRaises(DomainError):
                decode_raster(stream.getvalue())

    def test_byte_limit_before_open_and_output_limit(self):
        with patch("app.photos.validation.Image.open") as opened:
            with self.assertRaises(DomainError) as error:
                decode_raster(b"x" * (MAX_BYTES + 1))
            self.assertEqual(error.exception.code, "PAYLOAD_TOO_LARGE")
            opened.assert_not_called()
        raw = image_bytes()
        with patch("app.photos.validation.MAX_BYTES", len(raw)):
            # Conversion to RGBA PNG increases this generated image's encoding.
            with self.assertRaises(DomainError) as error:
                decode_raster(raw)
            self.assertEqual(error.exception.code, "PAYLOAD_TOO_LARGE")

    def test_pixel_limit_before_load(self):
        raw = bytearray(image_bytes())
        raw[16:24] = struct.pack(">II", 5001, 4000)
        raw[29:33] = struct.pack(">I", zlib.crc32(raw[12:29]))
        with patch("PIL.PngImagePlugin.PngImageFile.load") as load:
            with self.assertRaises(DomainError) as error:
                decode_raster(bytes(raw))
            self.assertEqual(error.exception.code, "PAYLOAD_TOO_LARGE")
            load.assert_not_called()

    def test_global_decode_budget_recovers(self):
        validation._DECODE_SLOTS.acquire()
        try:
            with self.assertRaises(PhotoUnavailable):
                decode_raster(image_bytes())
        finally:
            validation._DECODE_SLOTS.release()
        self.assertTrue(decode_raster(image_bytes()).data)

    def test_strict_fields_and_normalization(self):
        before = parse_fields(fields())
        self.assertIsNone(before.order_id)
        after = parse_fields(fields(purpose="after", order_id=ORDER, assignment_revision="1"))
        self.assertEqual(after.assignment_revision, 1)
        invalid = [fields(expected_version="00"), fields(file_valid="true"), fields(owner_id=SECTION),
                   fields(purpose="after"), fields(order_id=ORDER), fields(purpose="other"),
                   fields(purpose="after", order_id=ORDER, assignment_revision="01"),
                   fields(purpose="after", order_id=ORDER, assignment_revision="2147483648"),
                   fields(expected_version=0)]
        for form in invalid:
            with self.subTest(form=form), self.assertRaises(DomainError):
                parse_fields(form)

    def test_hash_canonical_fields_and_exact_raw_bytes(self):
        raw = image_bytes()
        request = parse_fields(fields())
        original = request_hash(request, raw)
        self.assertEqual(original, request_hash(parse_fields(dict(reversed(list(fields().items())))), raw))
        self.assertNotEqual(original, request_hash(request, raw + b"untrusted-trailing-bytes"))
        self.assertNotEqual(original, request_hash(parse_fields(fields(section_id=ORDER)), raw))


class MultipartTests(unittest.TestCase):
    def parse(self, parts, *, truncate=0, chunk_size=7):
        raw = multipart(parts)
        if truncate:
            raw = raw[:-truncate]
        parser = UploadParser("multipart/form-data; boundary=bounded-test")
        for position in range(0, len(raw), chunk_size):
            parser.write(raw[position:position + chunk_size])
        return parser.result()

    def parts(self):
        return [(k, v, None, None) for k, v in fields().items()] + [("file", image_bytes(), "../../x.png", "image/png")]

    def test_chunked_valid_filename_is_discarded(self):
        form, raw, mime = self.parse(self.parts())
        self.assertEqual(form, fields())
        self.assertEqual(raw, image_bytes())
        self.assertEqual(mime, "image/png")

    def test_duplicate_unknown_missing_and_extra_file(self):
        for parts in [self.parts() + [("purpose", "after", None, None)],
                      self.parts() + [("file_valid", "true", None, None)],
                      self.parts() + [("file", image_bytes(), "second.png", "image/png")],
                      self.parts()[:-1], [("purpose", "before", "x", None)]]:
            with self.subTest(parts=len(parts)), self.assertRaises(DomainError):
                self.parse(parts)

    def test_truncated_and_total_limit(self):
        with self.assertRaises(DomainError):
            self.parse(self.parts(), truncate=10)
        parser = UploadParser("multipart/form-data; boundary=x")
        with self.assertRaises(DomainError) as error:
            parser.write(b"x" * (MAX_REQUEST_BYTES + 1))
        self.assertEqual(error.exception.code, "PAYLOAD_TOO_LARGE")

    def test_part_limit_and_malformed_boundaries(self):
        parts = self.parts()
        parts[-1] = ("file", b"x" * (MAX_BYTES + 1), "x", None)
        with self.assertRaises(DomainError) as error:
            self.parse(parts, chunk_size=65536)
        self.assertEqual(error.exception.code, "PAYLOAD_TOO_LARGE")
        for header in (None, "image/png", "multipart/form-data", "multipart/form-data; boundary=a; boundary=b",
                       "multipart/form-data; boundary=" + "a" * 71):
            with self.subTest(header=header), self.assertRaises(DomainError):
                UploadParser(header)

    def test_duplicate_disposition_headers_and_params(self):
        base = multipart(self.parts())
        for body in [base.replace(b'name="purpose"', b'name="purpose"; name="file"'),
                     base.replace(b'name="purpose"\r\n', b'name="purpose"\r\nContent-Disposition: form-data; name="purpose"\r\n')]:
            parser = UploadParser("multipart/form-data; boundary=bounded-test")
            with self.assertRaises(DomainError):
                parser.write(body)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = PrivateFileStore(self.root)

    def test_private_content_generated_key_and_restart(self):
        raw = decode_raster(image_bytes()).data
        key = self.store.put(raw)
        self.assertRegex(key, r"^[a-f0-9]{32}\.img$")
        self.assertEqual(PrivateFileStore(self.root).get(key), raw)
        self.assertEqual((self.root / key).stat().st_mode & 0o777, 0o600)
        self.assertFalse(list(self.root.glob(".pending-*")))

    def test_reject_path_traversal_symlinks_hardlinks_and_unprivate_root(self):
        for key in ("../secret", "/etc/passwd", "bad.img"):
            with self.assertRaises(PhotoUnavailable):
                self.store.get(key)
        key = "a" * 32 + ".img"
        (self.root / key).symlink_to("/etc/passwd")
        with self.assertRaises(PhotoUnavailable):
            self.store.get(key)
        (self.root / key).unlink()
        real = self.store.put(b"synthetic-bytes")
        os.link(self.root / real, self.root / key)
        with self.assertRaises(PhotoUnavailable):
            self.store.get(real)
        self.root.chmod(0o755)
        with self.assertRaises(ValueError):
            PrivateFileStore(self.root)

    def test_budget_counts_orphans_and_pending(self):
        store = PrivateFileStore(self.root, max_total_bytes=MAX_BYTES)
        (self.root / ".pending-crash").write_bytes(b"x" * MAX_BYTES)
        with self.assertRaises(PhotoUnavailable):
            store.put(b"x")
        self.assertEqual((self.root / ".pending-crash").stat().st_size, MAX_BYTES)

    def test_failure_before_publish_cleans_only_temporary(self):
        original = self.store.put(b"existing")
        with patch("app.photos.storage.os.link", side_effect=OSError("synthetic publication failure")):
            with self.assertRaises(PhotoUnavailable):
                self.store.put(b"new")
        self.assertEqual(self.store.get(original), b"existing")
        self.assertFalse(list(self.root.glob(".pending-*")))

    def test_unknown_durability_after_publish_retains_final(self):
        real_fsync = os.fsync
        calls = 0
        def fail_directory(fd):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("synthetic fsync result unknown")
            real_fsync(fd)
        with patch("app.photos.storage.os.fsync", side_effect=fail_directory):
            with self.assertRaises(PhotoUnavailable):
                self.store.put(b"possibly-published")
        published = list(self.root.glob("*.img"))
        self.assertEqual(len(published), 1)
        self.assertEqual(published[0].read_bytes(), b"possibly-published")


if __name__ == "__main__":
    unittest.main()
