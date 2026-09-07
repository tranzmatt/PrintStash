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
