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

Policy saves support `expected_revision`; a stale editor receives
`audit_policy_revision_conflict` (409), and Settings always supplies its loaded
revision. Pause, skip, policy edits, manual starts, cancellation and automatic
repair attempts leave administrative audit entries. Optional jitter is stable
for the due slot and policy revision and leaves at least one minute of the
window. Launch retries start after 60 seconds and back off to 30 minutes, plus
configured jitter, while preserving the due slot. The maximum lateness defaults
to 120 minutes and determines overdue health and a single durable overdue event
per policy revision and missed slot. Pausing suppresses overdue execution and
health without erasing the due slot.

Notification policy selects a minimum severity and optional channel IDs (an
empty list uses every subscribed channel). Severity filtering considers only
new or worsened findings; an old critical finding does not promote a new
warning. Failed, cancelled, overdue and unsuccessful repair outcomes have
separate subscription events. Turning the policy threshold off suppresses all
its deliveries while retaining event evidence. The default minimum spacing is
60 minutes: deliveries are durably scheduled with that spacing, including
recovery, while transport retries retain the existing dispatcher semantics.
Notifications carry safe counts, categories, elapsed duration and an authenticated
Maintenance navigation path, without exposing Artifact names or storage keys.
A receiver may see a repeated transport delivery if a process stops after send
but before recording acknowledgement; durable event creation itself is unique.

Full runs record `planned_bytes` from the committed owned-object inventory
before execution, and `bytes_read` from authoritative read callbacks. Unknown
sizes are excluded from the estimate, and decompression, retries and repair
verification can make actual reads differ from planned bytes. A cached Artifact
never substitutes for authoritative audit reads.

Detailed finding rows expire after 90 days. The newest successful comparison
run for every mode/scope/storage generation and its immediately referenced
baseline retain their details, as do active runs. Compact run summaries,
immutable comparison digests and durable event evidence remain indefinitely;
pruning old detail rows never changes a regression baseline or its counts.
Process diagnostics expose bounded-label audit gauges for retained run outcomes,
duration, bytes, finding severity/category, current deferrals/overdue state,
notification evidence and recorded repair outcomes. There are no resource IDs,
paths or policy revisions in metric labels. Detailed health also includes
policy enabled/paused state, last-success age and latest run result.

Implementation verification maps the issue's phases to focused behavior tests:

| Requirement | Implementation | Verification |
| --- | --- | --- |
| Existing Quick/Full phases, manual repairs and restart behavior | Shared `vault_audit` executor and capacity callbacks | Existing audit tests; scheduled Full real-backup E2E |
| Persisted opt-in cadence, DST, jitter and missed slots | Policy calendar and `4b21cbe868b6` / `71bd0ebbf381` migrations | Calendar unit tests; policy integration tests; populated SQLite/PostgreSQL upgrades |
| Revision compare-and-set, one manual/scheduled admission | Conditional revision update and unique active claim | Concurrent two-session SQLite/PostgreSQL admission and policy-edit tests |
| Maintenance deferral, retry/backoff and overdue | Local scheduler and durable policy state | Runtime shutdown/gate tests; overdue and launch retry integration tests |
| Planned/actual owned bytes, rate and deadline | Inventory estimate and shared authoritative read callbacks | Byte estimate, deadline, bandwidth and cancellation tests; Full backup E2E |
| Comparable successful baseline, regression and ignored state | Immutable finding digests scoped by mode/storage generation | Comparison unit tests; failed/cancelled/incomparable baseline integration tests |
| Storage events, safe payload, preferences, spacing and retries | Existing transactional notification outbox and dispatcher | Threshold/channel, cooldown, terminal rollback/dedup tests; real notification-fake E2E |
| Opt-in verified Metadata/thumbnail repairs | Narrow managed-local allowlist with post-verification | Rejected unsafe/hash-mismatch repairs, failed repair evidence, both repair E2Es |
| Completed result remains cancelable during automatic repair | `auto_repair` phase retains the admission claim without changing baseline eligibility | Lifecycle, API cancellation, restart reconciliation and component polling tests |
| Settings controls, history and detailed health | Audit schedule card and policy diagnostics | Component controls/save/recovery tests; actual Settings Chromium persistence test |
| Bounded metrics and retention preserving evidence | Audit observability owner | Retention baseline and persisted metric assertions |
| Administrative evidence | Policy, skip, run, cancel and repair audit entries | Stale-editor transaction and repair failure log assertions |

An ignored finding stays in the immutable observation at its original severity.
An unchanged recurrence is quiet; a changed resource identity or worse severity
is evaluated as a new regression. Display-name changes cannot alter a receipt's
identity. Failed repair attempts leave the finding open and emit a deduplicated
repair-failed event; they are attempted once per run, with no retry loop.

Set `VAULT_PUBLIC_URL=https://your-printstash.example` to include an absolute
Maintenance link in notifications. Without an operator-supplied URL, messages
carry the application-relative `/settings?section=maintenance` path. Credentials,
query strings and fragments are never accepted in the configured base URL.
