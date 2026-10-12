"""Nonblocking parser slots shared by web processes in one runtime namespace.

Keep the files: unlinking an active lock could create a second lock inode.
Closing the descriptor (including process death) releases the OS lease.
"""

import errno
import os
import stat
from contextlib import contextmanager
from pathlib import Path
from tempfile import gettempdir

from ..service import fail


@contextmanager
def slot(limit):
    descriptor = None
    try:
        folder = Path(gettempdir()) / "assetcore-parser-slots"
        folder.mkdir(mode=0o700, exist_ok=True)
        info = folder.lstat()
        if not stat.S_ISDIR(info.st_mode) or (os.name != "nt" and
                (info.st_uid != os.getuid() or info.st_mode & 0o077)):
            raise OSError("Unsafe parser capacity directory")
        for index in range(limit):
            flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
            candidate = os.open(folder / f"slot-{index}", flags, 0o600)
            try:
                info = os.fstat(candidate)
                if not stat.S_ISREG(info.st_mode) or (os.name != "nt" and
                        (info.st_uid != os.getuid() or info.st_mode & 0o077)):
                    raise OSError("Unsafe parser capacity file")
                try:
                    if os.name == "nt":
                        import msvcrt
                        if info.st_size == 0:
                            os.write(candidate, b"\0")
                        os.lseek(candidate, 0, os.SEEK_SET)
                        msvcrt.locking(candidate, msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(candidate, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as error:
                    if error.errno not in {errno.EACCES, errno.EAGAIN}:
                        raise
                    continue
                descriptor = candidate
                break
            finally:
                if descriptor != candidate:
                    os.close(candidate)
        if descriptor is None:
            raise fail("catalog_extraction_busy")
        yield descriptor
    except OSError:
        raise fail("catalog_extraction_resource_limit", 422) from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
