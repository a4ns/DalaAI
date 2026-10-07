"""Private local volume adapter. No static URLs, client paths or delete API.

Publish before DB commit; rollback/unknown commit may leave a bounded orphan.
Never compensate an uncertain database commit by deleting its final object.
The deployment provisions a private 0700 UID-owned root on a durable volume.
"""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import re
import stat
from uuid import uuid4

from .validation import MAX_BYTES, PhotoUnavailable

_KEY = re.compile(r"[a-f0-9]{32}\.img")


class PrivateFileStore:
    def __init__(self, root, *, max_total_bytes=1024 * 1024 * 1024):
        self.root = Path(root)
        if not self.root.is_absolute() or type(max_total_bytes) is not int or max_total_bytes < MAX_BYTES:
            raise ValueError("Private absolute storage root and bounded capacity required")
        self.max_total_bytes = max_total_bytes
        # Fail at startup rather than silently creating an insecure directory.
        with self._directory():
            pass

    @contextmanager
    def _directory(self):
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise ValueError("Photo storage must be owned by this UID with mode 0700")
            yield fd
        finally:
            os.close(fd)

    def put(self, data):
        if type(data) is not bytes or not 0 < len(data) <= MAX_BYTES:
            raise ValueError("Store accepts bounded validated bytes only")
        key = uuid4().hex + ".img"
        temporary = ".pending-" + uuid4().hex
        try:
            with self._directory() as directory:
                lock = os.open(".store-lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=directory)
                try:
                    if not stat.S_ISREG(os.fstat(lock).st_mode) or os.fstat(lock).st_nlink != 1:
                        raise PhotoUnavailable()
                    fcntl.flock(lock, fcntl.LOCK_EX)
                    # Includes orphan and pending bytes; absent cleanup cannot
                    # silently grow beyond the configured capacity on this volume.
                    used = 0
                    for name in os.listdir(directory):
                        info = os.stat(name, dir_fd=directory, follow_symlinks=False)
                        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                            raise PhotoUnavailable()
                        used += info.st_size
                    if used + len(data) > self.max_total_bytes:
                        raise PhotoUnavailable()
                    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=directory)
                    try:
                        with os.fdopen(fd, "wb") as stream:
                            stream.write(data)
                            stream.flush()
                            os.fsync(stream.fileno())
                        # link is an atomic, exclusive publication: no overwrite.
                        os.link(temporary, key, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
                    finally:
                        # Only our unpublished staging name; never a final key.
                        os.unlink(temporary, dir_fd=directory)
                    os.fsync(directory)
                finally:
                    os.close(lock)
            return key
        except OSError:
            raise PhotoUnavailable() from None

    def get(self, key):
        if not isinstance(key, str) or not _KEY.fullmatch(key):
            raise PhotoUnavailable()
        try:
            with self._directory() as directory:
                fd = os.open(key, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
                with os.fdopen(fd, "rb") as stream:
                    info = os.fstat(stream.fileno())
                    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                            or info.st_uid != os.geteuid() or info.st_mode & 0o077
                            or not 0 < info.st_size <= MAX_BYTES):
                        raise PhotoUnavailable()
                    data = stream.read(MAX_BYTES + 1)
                    if len(data) != info.st_size:
                        raise PhotoUnavailable()
                    return data
        except OSError:
            raise PhotoUnavailable() from None
