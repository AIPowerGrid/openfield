"""POSIX writer/maintenance leases; lock files are never unlinked or repaired."""

import errno
import os
import stat
from contextlib import contextmanager
from pathlib import Path


class StoreBusy(ValueError):
    def __init__(self):
        super().__init__(
            "The store has active writers or maintenance. Try again later."
        )


def private_root(root: Path) -> Path:
    info = root.lstat()
    if (
        not root.is_absolute()
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
    ):
        raise ValueError("Use an existing, private owner-only store directory.")
    return root


@contextmanager
def file_lease(path: Path, *, shared=False, private=True):
    if os.name != "posix":
        raise ValueError("Store maintenance requires POSIX filesystem locks.")
    import fcntl

    fd = os.open(
        path,
        os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
        0o600,
    )
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or info.st_mode & (0o077 if private else 0o022)
        ):
            raise ValueError("The store lock has unsafe ownership or permissions.")
        try:
            fcntl.flock(
                fd, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB
            )
        except OSError as error:
            if error.errno in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK):
                raise StoreBusy() from None
            raise
        current = path.lstat()
        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
            raise ValueError("The store lock changed while acquiring it.")
        yield fd
    finally:
        # Closing, rather than explicitly unlocking, preserves an exec-inherited
        # lease until the foreground maintenance command itself exits.
        os.close(fd)


def store_activity(root: Path, *, shared=True):
    return file_lease(private_root(root) / ".store-activity.lock", shared=shared)
