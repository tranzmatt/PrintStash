import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Localized } from "@/components/ui/localized";
import { artifactCacheApi, type ArtifactCacheRead } from "@/lib/api/artifact-cache";
import { toast } from "@/lib/toast";

const LIMITS = [
  { name: "max_bytes", label: "Maximum cache bytes", min: 0 },
  { name: "headroom_bytes", label: "Minimum free bytes", min: 0 },
  { name: "max_entries", label: "Maximum cached files", min: 0 },
  { name: "max_fills", label: "Concurrent downloads", min: 1 },
  { name: "fill_wait_seconds", label: "Maximum wait for an active download (seconds)", min: 0 },
  {
    name: "verify_every_hits",
    label: "Recheck digest every N reads (0 disables sampling)",
    min: 0,
  },
] as const;

export function ArtifactCacheCard({ api = artifactCacheApi }: { api?: typeof artifactCacheApi }) {
  const [value, setValue] = useState<ArtifactCacheRead | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    api
      .read()
      .then((result) => {
        if (active) setValue(result);
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
    };
  }, [api]);
  const pending = Boolean(value?.usage.maintenance_running || value?.usage.pending_eviction_bytes);
  useEffect(() => {
    if (!pending) return;
    let active = true;
    const timer = window.setInterval(() => {
      void api
        .read()
        .then((result) => {
          if (active) {
            setValue((current) =>
              current
                ? {
                    ...current,
                    usage: result.usage,
                    health: result.health,
                    available: result.available,
                  }
                : result,
            );
            setFailed(false);
          }
        })
        .catch(() => {
          if (active) setFailed(true);
        });
    }, 1000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [api, pending]);

  async function perform(action: () => Promise<ArtifactCacheRead>) {
    setBusy(true);
    try {
      setValue(await action());
      setFailed(false);
      toast.success("Artifact cache settings updated.");
    } catch (error) {
      toast.error(error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Localized>
      <Card>
        <CardHeader>
          <CardTitle>Remote Artifact cache</CardTitle>
          <CardDescription>
            Reuse verified remote files for previews, printing, and downloads. Original files remain
            in Vault storage.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {failed && (
            <div role="alert" className="space-y-2">
              <p>Cache settings could not be loaded.</p>
              <Button variant="outline" disabled={busy} onClick={() => void perform(api.read)}>
                Retry
              </Button>
            </div>
          )}
          {!failed && !value && (
            <p role="status" className="text-sm text-muted-foreground">
              Loading cache settings…
            </p>
          )}
          {value && (
            <form
              className="space-y-4"
              onSubmit={(event) => {
                event.preventDefault();
                void perform(() => api.save(value.policy));
              }}
            >
              <label className="flex items-center gap-3">
                <Checkbox
                  checked={value.policy.enabled}
                  disabled={busy}
                  ariaLabel="Enable remote Artifact cache"
                  onChange={(checked) =>
                    setValue({ ...value, policy: { ...value.policy, enabled: checked === true } })
                  }
                />
                <span>Enable remote Artifact cache</span>
              </label>
              <p className="text-xs text-muted-foreground">
                Disabling stops new cache use. Active reads can finish. Clear cached files
                separately to reclaim space.
              </p>
              <p className="text-sm text-muted-foreground">
                Policy source:{" "}
                {value.source === "database" ? "Saved settings" : "Environment defaults"}. Limits
                apply immediately; changing the folder requires a restart.
              </p>
              <div className="grid gap-4 sm:grid-cols-2">
                {LIMITS.map(({ name, label, min }) => (
                  <label className="space-y-1" key={name}>
                    <span className="block text-sm">{label}</span>
                    <Input
                      required
                      type="number"
                      min={min}
                      step={1}
                      value={value.policy[name]}
                      disabled={busy}
                      onChange={(event) =>
                        setValue({
                          ...value,
                          policy: { ...value.policy, [name]: event.target.valueAsNumber },
                        })
                      }
                    />
                  </label>
                ))}
              </div>
              <label className="block space-y-1">
                <span className="text-sm">Cache folder (restart required)</span>
                <Input
                  required
                  value={value.policy.root}
                  disabled={busy}
                  onChange={(event) =>
                    setValue({ ...value, policy: { ...value.policy, root: event.target.value } })
                  }
                />
              </label>
              {value.restart_required && (
                <p role="status" className="text-sm text-warning">
                  Restart PrintStash to use the new cache folder.
                </p>
              )}
              {!value.available && (
                <p className="text-sm text-muted-foreground">
                  The cache is unavailable. Files are read from their original storage.
                </p>
              )}
              <p className="text-sm tabular-nums text-muted-foreground">
                {value.usage.bytes ?? 0} bytes cached · {value.usage.entries ?? 0} files ·{" "}
                {value.usage.leases ?? 0} active reads
              </p>
              <dl className="grid grid-cols-2 gap-3 text-sm tabular-nums sm:grid-cols-3">
                {[
                  ["Maximum bytes", value.policy.max_bytes],
                  ["Hit ratio", `${value.usage.hit_ratio_percent ?? 0}%`],
                  ["Provider bytes saved", value.usage.bytes_saved ?? 0],
                  ["Cache hits", value.usage.hits ?? 0],
                  ["Cache misses", value.usage.misses ?? 0],
                  ["Completed downloads", value.usage.completed_fills ?? 0],
                  ["Publication failures", value.usage.publication_failures ?? 0],
                  ["Corruptions", value.usage.corruptions ?? 0],
                  ["Cache errors", value.usage.errors ?? 0],
                  ["Evictions", value.usage.evictions ?? 0],
                  ["Bypasses", value.usage.bypasses ?? 0],
                ].map(([label, count]) => (
                  <div key={label}>
                    <dt className="text-muted-foreground">{label}</dt>
                    <dd>{count}</dd>
                  </div>
                ))}
              </dl>
              <p className="text-xs text-muted-foreground">
                Last verification:{" "}
                {value.usage.last_verification
                  ? new Date(value.usage.last_verification * 1000).toLocaleString()
                  : "No cached files verified yet"}
                .
              </p>
              {value.health !== "ready" && value.health !== "disabled" && (
                <p role="status" className="text-sm text-warning">
                  Cache needs attention ({value.health.replaceAll("_", " ")}). Original Vault
                  storage remains authoritative.
                </p>
              )}
              <p className="text-xs text-muted-foreground">
                Representation: {value.labels.representation} · Storage provider:{" "}
                {value.labels.backend}
              </p>
              {(Boolean(value.usage.maintenance_running) ||
                Boolean(value.usage.pending_eviction_bytes)) && (
                <p role="status" className="text-sm text-muted-foreground">
                  Reclaiming cache space. {value.usage.pending_eviction_bytes ?? 0} bytes wait for
                  active reads to finish.
                </p>
              )}
              <div className="flex flex-wrap gap-2">
                <Button type="submit" disabled={busy}>
                  Save cache settings
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  disabled={busy}
                  onClick={() => void perform(api.reset)}
                >
                  Reset to environment defaults
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  disabled={busy}
                  onClick={() => void perform(api.clear)}
                >
                  Clear cached files
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                Files in use stay available until their active reads finish. Clearing does not
                remove your Artifacts.
              </p>
            </form>
          )}
        </CardContent>
      </Card>
    </Localized>
  );
}
