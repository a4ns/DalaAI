"""Bounded strict streaming multipart parser; filenames are discarded.

No Request.form() spooling before authentication, and no trusted Content-Length.
Only the contract's fields and a single binary file are accepted.
"""
from email.message import Message
import re

from python_multipart import MultipartParser
from python_multipart.exceptions import MultipartParseError

from app.orders.models import DomainError
from .validation import MAX_BYTES

MAX_REQUEST_BYTES = MAX_BYTES + 65536
_FIELDS = {"operation_id", "section_id", "purpose", "expected_version", "order_id", "assignment_revision", "file"}


def _parameters(value):
    if not isinstance(value, str) or len(value) > 4096 or any(c in value for c in "\r\n\x00"):
        raise DomainError("INVALID_REQUEST", "Invalid multipart header")
    message = Message()
    message["Content-Type"] = value
    pairs = message.get_params(header="content-type", unquote=True)
    if not pairs:
        raise DomainError("INVALID_REQUEST", "Invalid multipart header")
    kind = pairs[0][0].lower()
    options = {}
    for key, val in pairs[1:]:
        key = key.lower()
        if key in options:
            raise DomainError("INVALID_REQUEST", "Duplicate multipart parameter")
        options[key] = val
    return kind, options


class UploadParser:
    def __init__(self, content_type):
        kind, parameters = _parameters(content_type)
        boundary = parameters.get("boundary")
        if kind != "multipart/form-data":
            raise DomainError("UNSUPPORTED_MEDIA_TYPE", "Multipart form required")
        if (set(parameters) != {"boundary"} or not isinstance(boundary, str)
                or not re.fullmatch(r"[0-9A-Za-z'()+_,./:=?-]{1,70}", boundary)):
            raise DomainError("INVALID_REQUEST", "Invalid multipart boundary")
        self.fields = {}
        self.file = None
        self.mime = None
        self.total = 0
        self.count = 0
        self.finished = False
        callbacks = {"on_" + name: getattr(self, name) for name in (
            "part_begin", "header_field", "header_value", "header_end", "headers_finished",
            "part_data", "part_end", "end")}
        self.parser = MultipartParser(boundary, callbacks, max_size=MAX_REQUEST_BYTES,
                                      max_header_count=4, max_header_size=4096)

    def write(self, chunk):
        self.total += len(chunk)
        if self.total > MAX_REQUEST_BYTES:
            raise DomainError("PAYLOAD_TOO_LARGE", "Upload exceeds the request limit")
        try:
            self.parser.write(chunk)
        except MultipartParseError:
            raise DomainError("INVALID_REQUEST", "Malformed multipart body") from None

    def part_begin(self):
        self.count += 1
        if self.count > 7:
            raise DomainError("INVALID_REQUEST", "Too many multipart parts")
        self.headers = {}
        self.header_name = bytearray()
        self.header_content = bytearray()
        self.data = bytearray()
        self.name = None

    def header_field(self, data, start, end):
        self.header_name.extend(data[start:end])

    def header_value(self, data, start, end):
        self.header_content.extend(data[start:end])

    def header_end(self):
        name = bytes(self.header_name).lower()
        if name not in (b"content-disposition", b"content-type") or name in self.headers:
            raise DomainError("INVALID_REQUEST", "Unexpected or duplicate multipart header")
        self.headers[name] = bytes(self.header_content).decode("latin-1")
        self.header_name.clear()
        self.header_content.clear()

    def headers_finished(self):
        kind, parameters = _parameters(self.headers.get(b"content-disposition"))
        name = parameters.get("name")
        if (kind != "form-data" or not isinstance(name, str) or name not in _FIELDS
                or set(parameters) - {"name", "filename"}
                or name in self.fields or (name == "file" and self.file is not None)):
            raise DomainError("INVALID_REQUEST", "Unknown or duplicate multipart field")
        if name == "file":
            if "filename" not in parameters:
                raise DomainError("INVALID_REQUEST", "Binary file part required")
            self.mime = self.headers.get(b"content-type")
            if self.mime is not None:
                self.mime = self.mime.lower().strip()
        elif "filename" in parameters:
            raise DomainError("INVALID_REQUEST", "Unexpected file part")
        self.name = name

    def part_data(self, data, start, end):
        limit = MAX_BYTES if self.name == "file" else 128
        if len(self.data) + end - start > limit:
            code = "PAYLOAD_TOO_LARGE" if self.name == "file" else "INVALID_REQUEST"
            raise DomainError(code, "Multipart part exceeds its limit")
        self.data.extend(data[start:end])

    def part_end(self):
        if self.name == "file":
            self.file = bytes(self.data)
        else:
            try:
                self.fields[self.name] = bytes(self.data).decode("utf-8", errors="strict")
            except UnicodeError:
                raise DomainError("INVALID_REQUEST", "Form fields must be UTF-8") from None
        self.data.clear()

    def end(self):
        self.finished = True

    def result(self):
        self.parser.finalize()
        # python-multipart.finalize alone currently does not check truncation.
        if not self.finished or self.file is None:
            raise DomainError("INVALID_REQUEST", "Incomplete multipart upload")
        return self.fields, self.file, self.mime
