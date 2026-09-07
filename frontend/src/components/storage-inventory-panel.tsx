import { useCallback, useEffect, useState } from "react";
import { HardDrive, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ConfirmModal } from "@/components/ui/confirm-modal";
import { Localized } from "@/components/ui/localized";
import {
  cleanupStorageStaging,
  getStorageInventory,
  sampleStorageInventory,
  type StorageInventoryReport,
} from "@/lib/api/storage-inventory";

function bytes(value: number | null): string {
  if (value === null) return "Unknown";
  return new Intl.NumberFormat(undefined, {
    style: "unit",
    unit: "gigabyte",
    maximumFractionDigits: 2,
  }).format(value / 1024 ** 3);
}

export function StorageInventoryPanel() {
  const [report, setReport] = useState<StorageInventoryReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      const current = await getStorageInventory();
      setReport(current);
      setError(false);
    } catch {
      setError(true);
    }
  }, []);
  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect -- state updates follow the request continuation.
    void load();
  }, [load]);

  async function refresh() {
    setBusy(true);
    try {
      await sampleStorageInventory();
      await load();
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }
  async function cleanup() {
    setBusy(true);
    try {
      const cleaned = await cleanupStorageStaging();
      setResult(
        `${cleaned.files_removed} files removed; ${cleaned.leases_removed} expired leases cleared.`,
      );
      setConfirm(false);
      await load();
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }
  const current = report?.inventory;
  const samples = [...(report?.history ?? [])].reverse();
  const largestSample = Math.max(1, ...samples.map((sample) => sample.owned_bytes));
  const historyPoints = samples
    .map(
      (sample, index) =>
        `${12 + (index * 576) / Math.max(1, samples.length - 1)},${108 - (sample.owned_bytes / largestSample) * 96}`,
    )
    .join(" ");
  return (
    <Localized>
      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-4 sm:px-5">
          <div className="flex min-w-0 items-center gap-3">
            <HardDrive className="h-8 w-8 rounded-md bg-muted p-2" />
            <div>
              <h2 className="text-sm font-semibold">Storage insights</h2>
              <p className="text-xs text-muted-foreground">
                Recorded usage, shared disk headroom, and growth history.
              </p>
            </div>
          </div>
          <Button variant="outline" size="sm" disabled={busy} onClick={refresh}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Refresh measurement
          </Button>
        </div>
        {error && (
          <div role="alert" className="border-b p-4 text-sm text-destructive">
            Storage insights could not be loaded. Retry the measurement.
          </div>
        )}
        {!current && !error && (
          <p role="status" className="p-4 text-sm text-muted-foreground">
            Loading storage insights…
          </p>
        )}
        {current && (
          <>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-3 border-b p-4 text-sm sm:grid-cols-4">
              {[
                ["Logical references", current.logical_bytes],
                ["Unique owned objects", current.unique_owned_bytes],
                ["External references", current.external_referenced_bytes],
                ["Temporary staging", current.temporary_bytes],
              ].map(([label, value]) => (
                <div key={label}>
                  <dt className="text-xs text-muted-foreground">{label}</dt>
                  <dd className="mt-1 font-medium tabular-nums">{bytes(Number(value))}</dd>
                </div>
              ))}
            </dl>
            <div className="border-b px-4 py-3 text-xs text-muted-foreground">
              <p>
                Usage includes known sizes only. {current.unknown_object_count} objects have no
                recorded size. Provider totals: {bytes(current.measured_provider_bytes)}.
              </p>
              <p className="mt-1">
                Last saved measurement:{" "}
                {current.measured_at
                  ? new Date(current.measured_at).toLocaleString()
                  : "Not yet measured"}
                .
              </p>
            </div>
            <div className="divide-y divide-border">
              {current.volumes.map((volume) => (
                <div
                  key={volume.domain_id}
                  className="flex flex-wrap items-start justify-between gap-3 px-4 py-3 text-sm"
                >
                  <div>
                    <p className="font-medium capitalize">{volume.roles.join(" · ")}</p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Free: {bytes(volume.free_bytes)} · Reserved: {bytes(volume.reserved_bytes)} ·
                      Headroom: {bytes(volume.headroom_bytes)}
                    </p>
                  </div>
                  <p
                    className={
                      volume.status === "blocked" ? "text-destructive" : "text-muted-foreground"
                    }
                  >
                    {volume.status === "blocked"
                      ? "New allocations blocked"
                      : volume.status === "available"
                        ? "Capacity available"
                        : "Capacity unknown"}
                  </p>
                </div>
              ))}
            </div>
            <div className="border-t px-4 py-3">
              <h3 className="text-sm font-semibold">Usage by category</h3>
              <div className="mt-2 divide-y divide-border">
                {current.buckets
                  .filter((bucket) => bucket.logical_bytes > 0)
                  .map((bucket, index) => (
                    <div
                      key={`${bucket.category}-${bucket.lifecycle}-${index}`}
                      className="flex flex-wrap justify-between gap-2 py-2 text-xs"
                    >
                      <span>
                        {bucket.category} · {bucket.lifecycle}
                      </span>
                      <span className="tabular-nums">{bytes(bucket.logical_bytes)}</span>
                    </div>
                  ))}
                {current.logical_bytes === 0 && (
                  <p className="py-2 text-sm text-muted-foreground">No recorded library bytes.</p>
                )}
              </div>
            </div>
            <div className="border-t px-4 py-3">
              <h3 className="text-sm font-semibold">Growth forecast</h3>
              {samples.length > 1 && (
                <figure className="mt-3">
                  <svg
                    role="img"
                    aria-label="Recorded owned storage over time"
                    viewBox="0 0 600 120"
                    className="h-28 w-full text-primary"
                  >
                    <title>Recorded owned storage over time</title>
                    <polyline
                      points={historyPoints}
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                    />
                  </svg>
                  <figcaption className="flex justify-between text-xs text-muted-foreground">
                    <span>{new Date(samples[0].sampled_at).toLocaleDateString()}</span>
                    <span>{bytes(largestSample)} maximum</span>
                    <span>
                      {new Date(samples[samples.length - 1].sampled_at).toLocaleDateString()}
                    </span>
                  </figcaption>
                </figure>
              )}
              <p className="mt-1 text-xs text-muted-foreground">
                {report?.forecast.days_remaining !== null &&
                report?.forecast.days_remaining !== undefined
                  ? `Estimated ${Math.floor(report.forecast.days_remaining)} days of headroom at recent growth.`
                  : "A forecast needs seven daily samples spanning at least seven days, stable positive growth, and known capacity."}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {report?.history.length ?? 0} daily measurements retained. Forecasts do not
                authorize writes.
              </p>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3 border-t bg-muted/30 p-4">
              <div className="min-w-0">
                <p className="text-sm font-medium">Expired staging</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Remove only expired files whose ownership can still be verified.
                </p>
              </div>
              <Button variant="outline" size="sm" onClick={() => setConfirm(true)} disabled={busy}>
                Clean up expired staging
              </Button>
            </div>
            {result && (
              <p role="status" className="border-t p-4 text-sm">
                {result}
              </p>
            )}
          </>
        )}
        <ConfirmModal
          open={confirm}
          onClose={() => setConfirm(false)}
          onConfirm={() => void cleanup()}
          title="Clean up expired staging?"
          description="Only expired staging with verified ownership is eligible. Uncertain files are retained. This action is recorded in the audit log."
          confirmLabel="Clean up"
          busy={busy}
        />
      </Card>
    </Localized>
  );
}
