"""Verified, disposable disk representations with cross-process claims and leases.

The private SQLite index is cache metadata, never catalogue ownership. All file
selection, publication and removal is serialized with the index transaction.
Process incarnation tokens make abandoned claims recoverable without expiring a
live response merely because it is slow.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import ContextManager


class CacheUnavailable(RuntimeError):
    """Caching cannot safely admit this representation; use normal delivery."""


class RepresentationChanged(RuntimeError):
    """The authoritative transfer does not match the expected representation."""


@dataclass(frozen=True)
class Representation:
    kind: str
    version: int
    sha256: str
    size: int

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", self.kind):
            raise ValueError("invalid representation kind")
        if self.version < 1 or self.size < 0 or not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError("invalid representation identity")

    @property
    def key(self) -> str:
        return hashlib.sha256(f"{self.kind}:{self.version}:{self.sha256}:{self.size}".encode()).hexdigest()


@dataclass(frozen=True)
class CachePolicy:
    enabled: bool = False
    max_bytes: int = 10 * 1024**3
    max_entries: int = 10000
    max_fills: int = 2
    headroom_bytes: int = 1024**3
    verify_every_hits: int = 100


def _process_identity(pid: int) -> str | None:
    try:
        # starttime disambiguates PID reuse; proc is available on supported Linux.
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


class CacheLease:
    def __init__(self, cache: ArtifactMaterializer, token: str, path: Path):
        self.path = path
        self._cache = cache
        self._token = token

    def close(self) -> None:
        if self._token:
            token, self._token = self._token, ""
            self._cache.release(token)

    def __enter__(self) -> Path:
        return self.path

    def __exit__(self, *_: object) -> None:
        self.close()


class ArtifactMaterializer:
    def __init__(
        self,
        root: Path,
        policy: Callable[[], CachePolicy],
        reserve: Callable[[str, Path, int], ContextManager[object]] | None = None,
    ):
        self.root = root.absolute()
        self.policy = policy
        self.reserve = reserve
        self.pid = os.getpid()
        self.incarnation = _process_identity(self.pid)
        if self.incarnation is None:
            raise CacheUnavailable("process identity unavailable")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.is_symlink() or self.root.stat().st_uid != os.getuid():
            raise CacheUnavailable("cache root must be private")
        self.root.chmod(0o700)
        with self._transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS entries (
                    key TEXT PRIMARY KEY, size INTEGER NOT NULL, digest TEXT NOT NULL,
                    inode INTEGER NOT NULL, mtime INTEGER NOT NULL,
                    used REAL NOT NULL, hits INTEGER NOT NULL DEFAULT 0,
                    discarded INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS claims (
                    key TEXT PRIMARY KEY, token TEXT NOT NULL, size INTEGER NOT NULL,
                    pid INTEGER NOT NULL, incarnation TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS leases (
                    token TEXT PRIMARY KEY, key TEXT NOT NULL,
                    pid INTEGER NOT NULL, incarnation TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS metrics (name TEXT PRIMARY KEY, value INTEGER NOT NULL);
            """)
        self.reconcile()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.root / "index.sqlite3", timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _metric(self, db: sqlite3.Connection, name: str) -> None:
        db.execute("INSERT INTO metrics VALUES (?,1) ON CONFLICT(name) DO UPDATE SET value=MIN(value+1,9223372036854775806)", (name,))

    def _remove(self, db: sqlite3.Connection, key: str) -> bool:
        if db.execute("SELECT 1 FROM leases WHERE key=?", (key,)).fetchone():
            db.execute("UPDATE entries SET discarded=1 WHERE key=?", (key,))
            return False
        (self.root / f"{key}.blob").unlink(missing_ok=True)
        db.execute("DELETE FROM entries WHERE key=?", (key,))
        self._metric(db, "evictions")
        return True

    def reconcile(self) -> None:
        with self._transaction() as db:
            for table in ("leases", "claims"):
                for row in db.execute(f"SELECT * FROM {table}").fetchall():
                    if _process_identity(row["pid"]) != row["incarnation"]:
                        db.execute(f"DELETE FROM {table} WHERE token=?", (row["token"],))
            for row in db.execute("SELECT * FROM entries").fetchall():
                if row["discarded"] or not (self.root / f'{row["key"]}.blob').is_file():
                    self._remove(db, row["key"])
            known = {f'{r[0]}.blob' for r in db.execute("SELECT key FROM entries")}
            known.update(f'{str(r[0]).removeprefix("revoked:")}.tmp' for r in db.execute("SELECT token FROM claims"))
            for path in self.root.iterdir():
                if re.fullmatch(r"[0-9a-f]{64}\.blob|[0-9a-f]{32}\.tmp", path.name) and path.name not in known:
                    path.unlink(missing_ok=True)

    def acquire(self, representation: Representation) -> CacheLease | None:
        if not self.policy().enabled:
            return None
        with self._transaction() as db:
            row = db.execute("SELECT * FROM entries WHERE key=? AND discarded=0", (representation.key,)).fetchone()
            if row is None:
                self._metric(db, "misses")
                return None
            path = self.root / f"{representation.key}.blob"
            try:
                info = path.stat(follow_symlinks=False)
                valid = not path.is_symlink() and info.st_size == representation.size and info.st_ino == row["inode"] and info.st_mtime_ns == row["mtime"]
                sampling = self.policy().verify_every_hits
                if valid and sampling and row["hits"] % sampling == 0:
                    with path.open("rb") as stream:
                        valid = hashlib.file_digest(stream, "sha256").hexdigest() == representation.sha256
            except OSError:
                valid = False
            if not valid:
                self._metric(db, "errors")
                self._remove(db, representation.key)
                return None
            token = uuid.uuid4().hex
            db.execute("INSERT INTO leases VALUES (?,?,?,?)", (token, representation.key, self.pid, self.incarnation))
            db.execute("UPDATE entries SET used=?,hits=hits+1 WHERE key=?", (time.time(), representation.key))
            self._metric(db, "hits")
            return CacheLease(self, token, path)

    def release(self, token: str) -> None:
        with self._transaction() as db:
            row = db.execute("SELECT key FROM leases WHERE token=?", (token,)).fetchone()
            db.execute("DELETE FROM leases WHERE token=?", (token,))
            if row and db.execute("SELECT 1 FROM entries WHERE key=? AND discarded=1", (row[0],)).fetchone():
                self._remove(db, row[0])

    def clear(self) -> dict[str, int]:
        with self._transaction() as db:
            for row in db.execute("SELECT key FROM entries").fetchall():
                self._remove(db, row[0])
            # Revoke publication, but leave live writer's temp to its own finally.
            db.execute("UPDATE claims SET token='revoked:' || token WHERE token NOT LIKE 'revoked:%'")
        return self.status()

    def status(self) -> dict[str, int]:
        with self._transaction() as db:
            row = db.execute("SELECT COALESCE(SUM(size),0),COUNT(*) FROM entries").fetchone()
            claimed = db.execute("SELECT COALESCE(SUM(size),0),COUNT(*) FROM claims").fetchone()
            return {"bytes": row[0], "entries": row[1], "reserved_bytes": claimed[0], "fills": claimed[1], "leases": db.execute("SELECT COUNT(*) FROM leases").fetchone()[0], **{r[0]: r[1] for r in db.execute("SELECT * FROM metrics")}}

    def begin_fill(self, representation: Representation) -> CacheFill | None:
        policy = self.policy()
        if not policy.enabled or representation.size > policy.max_bytes:
            return None
        with self._transaction() as db:
            if db.execute("SELECT 1 FROM entries WHERE key=?", (representation.key,)).fetchone() or db.execute("SELECT 1 FROM claims WHERE key=?", (representation.key,)).fetchone():
                return None
            claims = db.execute("SELECT COALESCE(SUM(size),0),COUNT(*) FROM claims").fetchone()
            if claims[1] >= policy.max_fills:
                return None
            for row in db.execute("SELECT key,size FROM entries ORDER BY used").fetchall():
                total = db.execute("SELECT COALESCE(SUM(size),0),COUNT(*) FROM entries").fetchone()
                if total[0] + claims[0] + representation.size <= policy.max_bytes and total[1] + claims[1] < policy.max_entries:
                    break
                self._remove(db, row[0])
            total = db.execute("SELECT COALESCE(SUM(size),0),COUNT(*) FROM entries").fetchone()
            if total[0] + claims[0] + representation.size > policy.max_bytes or total[1] + claims[1] >= policy.max_entries or shutil.disk_usage(self.root).free - claims[0] - representation.size < policy.headroom_bytes:
                return None
            token = uuid.uuid4().hex
            db.execute("INSERT INTO claims VALUES (?,?,?,?,?)", (representation.key, token, representation.size, self.pid, self.incarnation))
        return CacheFill(self, representation, token)

    def filling(self, representation: Representation) -> bool:
        with self._transaction() as db:
            return db.execute("SELECT 1 FROM claims WHERE key=?", (representation.key,)).fetchone() is not None

    @contextmanager
    def materialize(self, representation: Representation, chunks: Callable[[], Iterator[bytes]]) -> Iterator[Path]:
        # Wait only on the same representation, never hold a database lock over IO.
        deadline = time.monotonic() + 300
        while True:
            lease = self.acquire(representation)
            if lease:
                with lease as path:
                    yield path
                return
            fill = self.begin_fill(representation)
            if fill:
                try:
                    for chunk in chunks():
                        fill.write(chunk)
                    lease = fill.complete()
                    if lease is None:
                        raise CacheUnavailable("fill publication revoked")
                finally:
                    fill.close()
                with lease as path:
                    yield path
                return
            if not self.filling(representation) or time.monotonic() >= deadline:
                raise CacheUnavailable("cache admission refused")
            threading.Event().wait(0.02)


class CacheFill:
    def __init__(self, cache: ArtifactMaterializer, representation: Representation, token: str):
        self.cache = cache
        self.representation = representation
        self.token = token
        self.path = cache.root / f"{token}.tmp"
        self.output = None
        self.reservation = None
        self.digest = hashlib.sha256()
        self.size = 0
        try:
            if cache.reserve:
                self.reservation = cache.reserve(token, cache.root, representation.size)
                self.reservation.__enter__()
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            self.output = os.fdopen(fd, "wb")
        except BaseException:
            self.close()
            raise

    def write(self, chunk: bytes) -> None:
        self.size += len(chunk)
        if self.size > self.representation.size:
            raise RepresentationChanged("representation size mismatch")
        if self.output is None:
            raise CacheUnavailable("fill closed")
        self.output.write(chunk)
        self.digest.update(chunk)

    def complete(self) -> CacheLease | None:
        if self.size != self.representation.size or self.digest.hexdigest() != self.representation.sha256:
            raise RepresentationChanged("representation digest mismatch")
        if self.output is None:
            raise CacheUnavailable("fill closed")
        self.output.flush()
        os.fsync(self.output.fileno())
        self.output.close()
        self.output = None
        with self.cache._transaction() as db:
            if not self.cache.policy().enabled or not db.execute("SELECT 1 FROM claims WHERE token=?", (self.token,)).fetchone():
                return None
            destination = self.cache.root / f"{self.representation.key}.blob"
            os.replace(self.path, destination)
            directory = os.open(self.cache.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            info = destination.stat()
            db.execute("INSERT INTO entries(key,size,digest,inode,mtime,used) VALUES (?,?,?,?,?,?)", (self.representation.key, self.size, self.representation.sha256, info.st_ino, info.st_mtime_ns, time.time()))
            db.execute("DELETE FROM claims WHERE token=?", (self.token,))
            lease_token = uuid.uuid4().hex
            db.execute("INSERT INTO leases VALUES (?,?,?,?)", (lease_token, self.representation.key, self.cache.pid, self.cache.incarnation))
            self.cache._metric(db, "completed_fills")
            return CacheLease(self.cache, lease_token, destination)

    def close(self) -> None:
        if self.output:
            self.output.close()
            self.output = None
        self.path.unlink(missing_ok=True)
        with self.cache._transaction() as db:
            db.execute("DELETE FROM claims WHERE token IN (?,?)", (self.token, f"revoked:{self.token}"))
        if self.reservation:
            self.reservation.__exit__(None, None, None)
            self.reservation = None
