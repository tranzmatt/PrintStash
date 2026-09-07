# Storage capacity and insights

Settings → Storage insights separates logical library references, external references,
known unique owned objects, staging leases, and backup replicas. Logical bytes count
references. Physical ownership is deduplicated by provider, namespace and object key;
two copies with the same SHA-256 still consume two allocations.

The inventory uses SQL aggregates and the existing ownership census. Opening Settings
or the dashboard never walks an object-store namespace. Recorded object sizes are an
estimate of owned bytes, not a provider's billed usage. Objects without recorded sizes
remain unknown. S3 free space and provider quota remain unknown when the provider does
not supply capacity evidence. Local free space comes from `statvfs` on the actual
filesystem; roots sharing one device share one capacity budget.

The maintenance tick saves at most one sample per UTC day. History keeps up to 366
daily samples per target. The forecast requires seven distinct daily samples spanning
at least seven days and positive, stable growth. It uses the median daily change,
withholds estimates around large outliers, and never authorizes an allocation.

## Admission policy

`VAULT_STORAGE_MIN_FREE_BYTES` defaults to 1 GiB. The configuration API accepts a
`storage_min_free_bytes` database override; `-1` resets it to the environment/default.
Existing upload type/byte limits, staging limits and per-user counts still apply.

Heavy operations reserve their peak additional allocations before writing. Claims on
one volume are summed and admitted under a database lock shared by all workers.
Reservations are durable on SQLite and PostgreSQL. Workflows renew before increasing
an estimate, and release after their final allocation. A rejected request returns
HTTP 507 with `storage_capacity_exceeded`; inaccessible or replaced volume evidence
also fails closed.

A reservation is a budget claim, never a deletion receipt. An expired claim remains
charged while its owner may still write. Workflow reconciliation can release a claim
only after proving the owner is terminal. On Linux, expired claims with persisted
host/boot/PID/start-time evidence are reclaimed after their process is demonstrably
gone. Foreign-host, live-process and unknown identities remain charged.

The shared interface is `CapacityManager(session_factory)` with `reserve`, `hold`,
`renew`, `release`, `serialize_admission(session)` and reconciliation operations in `app.modules.storage.capacity`.
Use `CapacityResource.for_path` for the actual staging/cache/output filesystem and
`for_quota` for a provider quota domain. Same-volume resources are added, so callers
must describe peak overlap of input, output and rollback bytes, without counting a
shared object as multiple allocations. Unknown provider capacity produces a warning;
it never grants additional local staging space.

## Cleanup

The **Clean up expired staging** action requires explicit confirmation and is audited.
It calls the existing staging owner: only expired files whose device/inode/ctime/size
still match their receipts can be removed. Replaced or uncertain files stay in place
and remain charged. Cleanup refreshes the saved inventory. Library artifacts, trash,
backups and other authoritative data are never automatically deleted by this policy.

The [behavior matrix](storage-capacity-test-matrix.md) records the feature verification.
