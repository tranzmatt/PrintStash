# Scheduled Vault audits

Administrators can enable weekly Quick and monthly Full audits in Settings →
Maintenance. Both schedules are disabled initially. Full audits require an
explicit cost acknowledgement: they read authoritative stored data and verify
owned backup archives, so remote storage can charge for transfers and requests.
Scheduling uses the existing Quick/Full auditor and its durable findings.

Each policy has an IANA timezone, local start time, window length, weekday or
day of month, pause control and skip-next action. A day beyond the end of a month
uses that month's final day. A daylight-saving gap advances to the first valid
minute; a repeated hour uses its first occurrence. Window length is elapsed
minutes from that instant. Pause preserves the due slot; skip advances it.

If the application misses several intervals, it starts at most one catch-up
audit, inside the next daily window. It does not replay each missed interval.
Manual and scheduled runs share a unique database admission claim. A successful
manual run begun within a due slot can satisfy that slot for the same mode.
Failed, cancelled or interrupted runs never advance the last-success time.

The local scheduler respects restore maintenance and unavailable storage, drains
on shutdown, and reconciles interrupted claims at startup. Reads are sequential.
Scheduled Artifact hashing and backup reads honor the configured byte rate and
check cancellation/deadlines between chunks. An already-started provider call
finishes within its transport timeout before cancellation can take effect.
Shared capacity reservations cover source materialization and backup staging;
backup verification rechecks capacity against the uncompressed database size
before creating its temporary database file.

Successful runs compare findings only with the latest successful run of the
same mode, scope and storage generation. Restore markers or a changed storage
target invalidate the old comparison baseline. Regression and recovery events
contain audit IDs and aggregate counts, never file names, paths or finding
payloads. Events and matching delivery rows commit together, with durable event
deduplication. Configure the existing notification master switch and channel
subscriptions for “Vault audit regression” and “Vault audit recovery”. Printer
filters continue to apply, so a channel restricted to particular printers does
not receive storage events. External delivery uses the existing retry policy
and is at least once.

Automatic repair is disabled and its allowlist is empty initially. The only
available automatic actions rebuild missing Metadata or missing/unreadable
thumbnails from live managed local Artifacts with verified authoritative
checksums. Remote and linked sources remain manual. Repairs never change
primary bytes, restore recommendation markers, retry imports, or delete data.
A successful repair is checked again before its finding is resolved and a
recovery event is recorded. Failed repairs retain their findings.

The history panel preserves failed attempts. Detailed authenticated health
includes last-success, next-due and overdue status; the minimal liveness probe
remains independent of audit health.

API: `GET /api/v1/maintenance/audit-policies`,
`PUT /api/v1/maintenance/audit-policies/{quick|full}`, and
`POST /api/v1/maintenance/audit-policies/{quick|full}/skip`. All policy controls
require an administrator. Existing audit start/history/finding endpoints remain
available, with additive trigger, deadline, comparison and bytes-read fields.
