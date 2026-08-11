from __future__ import annotations

from pathlib import Path
from typing import IO

try:
    import fcntl
except ImportError:  # pragma: no cover - Linux production path has fcntl
    fcntl = None


class ReplicaLockError(RuntimeError):
    pass


def acquire_sqlite_replica_lock(data_root: Path, *, enabled: bool) -> IO[str] | None:
    """Hold a non-blocking filesystem lock for the lifetime of a SQLite process.

    Railway/production must not run multiple workers against the same SQLite file.
    Keeping the handle open preserves the lock; callers close it during shutdown.
    """
    if not enabled or fcntl is None:
        return None
    data_root.mkdir(parents=True, exist_ok=True)
    lock_path = data_root / '.barsan-sqlite-single-replica.lock'
    handle = lock_path.open('a+', encoding='utf-8')
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise ReplicaLockError('SQLite single-replica lock is already held by another Barsan process.') from exc
    handle.seek(0)
    handle.truncate(0)
    handle.write('barsan-single-replica\n')
    handle.flush()
    return handle


def release_sqlite_replica_lock(handle: IO[str] | None) -> None:
    if handle is None:
        return
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def same_origin_allowed(origin: str | None, referer: str | None, allowed_origins: set[str]) -> bool:
    """Validate browser cookie-authenticated mutation requests against known origins."""
    candidate = (origin or '').strip().rstrip('/')
    if candidate:
        return candidate in allowed_origins
    ref = (referer or '').strip()
    if ref:
        return any(ref == base or ref.startswith(base + '/') for base in allowed_origins)
    return False
