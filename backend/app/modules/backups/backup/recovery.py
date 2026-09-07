"""Restart reconciliation of interrupted or uncertain restorations."""

from __future__ import annotations

import json

import app.modules.backups.backup.restore_journal as _restore_journal_module
from app.core.config import settings
from app.core.logging import get_logger
from app.runtime.maintenance import hold_restore_maintenance

logger = get_logger(__name__)


def inspect_restore_recovery() -> bool:
    """Put the process in restore maintenance when a restore was interrupted.

    A sidecar journal is deliberately treated as evidence of an unfinished
    operation across process restarts.  In particular, a database-swap intent
    cannot be safely inferred to be pre- or post-swap without querying the
    marker in the active database.  Keeping the gate set makes reads and
    operator recovery available while preventing background mutation work.
    """
    try:
        journals = sorted(settings.backup_dir.glob(".restore-*.journal"))
    except OSError:
        # An unreadable backup directory cannot prove that no restore journal
        # exists. Keep maintenance active until an operator can inspect or
        # repair the directory; clearing the gate here would allow writes to
        # race an unresolved restore.
        hold_restore_maintenance()
        return True
    if not journals:
        return False

    # Even a pre-PONR journal represents staged ownership and an operation
    # whose cleanup has not been proven. Gate mutations until the restore is
    # explicitly resumed or the journal is resolved.
    unresolved = bool(journals)
    for path in journals:
        try:
            state = _restore_journal_module._load_restore_journal(path)
        except Exception:
            unresolved = True
            continue
        if state.database_swap_intent or state.database_active:
            unresolved = True
            # A marker query failure is intentionally indistinguishable from
            # an active marker here: both require administrator recovery.
        if state.database_swap_intent:
            nonce = state.started.get("operation_nonce")
            archive_sha = state.started.get("archive_sha256")
            if not isinstance(nonce, str) or not isinstance(archive_sha, str):
                # An un-upgraded v1 journal cannot authorise a marker lookup;
                # leave maintenance active until the normal resume upgrades it.
                continue
            _restore_journal_module._active_restore_marker(
                str(state.started.get("backup_id", "")),
                operation_nonce=nonce,
                archive_sha256=archive_sha,
            )
    if unresolved:
        hold_restore_maintenance()
    return unresolved


def unresolved_restore_backup_id() -> str | None:
    """Return the only journaled backup allowed to resume recovery.

    ``None`` is returned when the journal is unreadable, malformed, or
    ambiguous.  Callers must fail closed in that case rather than allowing a
    new restore to bypass the unresolved operation.
    """
    try:
        journals = sorted(settings.backup_dir.glob(".restore-*.journal"))
    except OSError:
        return None
    if len(journals) != 1:
        return None
    path = journals[0]
    # The filename is the operation's durable routing identity.  A journal can
    # be corrupt, or can contain a tampered ``backup_id``; either case must be
    # routed to the operation named by the file so its normal parser returns a
    # precise invalid/mismatch conflict rather than the generic recovery gate.
    prefix, suffix = ".restore-", ".journal"
    name = path.name
    if not name.startswith(prefix) or not name.endswith(suffix):
        return None
    backup_id = name[len(prefix) : -len(suffix)]
    if not backup_id:
        return None
    # Route journals whose first record is still readable to the restore parser
    # so sequence corruption reports the precise ``restore_journal_invalid``
    # reason.  A completely unreadable first record has no trustworthy routing
    # identity and must remain fail-closed (no restore may bypass maintenance).
    try:
        first_line = path.read_bytes().splitlines()[0]
        started = json.loads(first_line.decode("utf-8"))
    except (IndexError, OSError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(started, dict):
        return None
    return backup_id


def _restore_journal_pending() -> bool:
    """Return whether any restore evidence still requires maintenance.

    The sidecar is the durable source of truth for the process gate.  A local
    boolean is not enough: a retry can fail before resolving an older journal,
    and clearing the gate in that case would let unrelated writes race the
    unresolved restore on the next request.
    """
    try:
        return any(settings.backup_dir.glob(".restore-*.journal"))
    except OSError:
        # An unreadable backup directory cannot prove resolution. Fail closed.
        return True
