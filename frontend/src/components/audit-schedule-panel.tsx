import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  listAuditPolicies,
  listVaultAudits,
  saveAuditPolicy,
  skipAuditSlot,
} from "@/lib/api/maintenance";
import { formatBytes } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import type { AuditPolicy, VaultAuditRun } from "@/types/maintenance";

function shownDate(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "—";
}

function PolicyForm({ initial, onSaved }: { initial: AuditPolicy; onSaved: () => void }) {
  const { t } = useI18n();
  const [policy, setPolicy] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const title = policy.mode === "quick" ? t("auditSchedule.quick") : t("auditSchedule.full");
  async function save() {
    setBusy(true);
    setError(null);
    try {
      setPolicy(await saveAuditPolicy(policy));
      onSaved();
    } catch {
      setError(t("auditSchedule.saveFailed"));
    } finally {
      setBusy(false);
    }
  }
  async function skip() {
    setBusy(true);
    try {
      setPolicy(await skipAuditSlot(policy.mode));
      onSaved();
    } catch {
      setError(t("auditSchedule.skipFailed"));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form
      id={`audit-policy-${policy.mode}`}
      aria-label={`${title} ${t("auditSchedule.schedule")}`}
      className="space-y-3 border-t border-border py-4"
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <div className="flex flex-wrap items-center gap-4">
        <h4 className="text-sm font-semibold">{title}</h4>
        <label className="flex items-center gap-2 text-sm">
          <Checkbox
            checked={policy.enabled}
            onChange={(enabled) => setPolicy({ ...policy, enabled })}
          />
          {t("auditSchedule.enabled")}
        </label>
        <label className="flex items-center gap-2 text-sm">
          <Checkbox
            checked={policy.paused}
            onChange={(paused) => setPolicy({ ...policy, paused })}
          />
          {t("auditSchedule.paused")}
        </label>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <label className="space-y-1 text-sm">
          {t("auditSchedule.cadence")}
          <select
            className="w-full rounded-md border border-input bg-background p-2"
            value={policy.cadence}
            onChange={(event) =>
              setPolicy({
                ...policy,
                cadence: event.target.value === "monthly" ? "monthly" : "weekly",
              })
            }
          >
            <option value="weekly">{t("auditSchedule.weekly")}</option>
            <option value="monthly">{t("auditSchedule.monthly")}</option>
          </select>
        </label>
        <label className="space-y-1 text-sm">
          {t("auditSchedule.jitter")}
          <Input
            type="number"
            min={0}
            max={3600}
            value={policy.jitter_seconds ?? 0}
            onChange={(event) =>
              setPolicy({ ...policy, jitter_seconds: Number(event.target.value) })
            }
          />
        </label>
        <label className="space-y-1 text-sm">
          {t("auditSchedule.lateness")}
          <Input
            type="number"
            min={1}
            max={44640}
            value={policy.max_lateness_minutes ?? 120}
            onChange={(event) =>
              setPolicy({ ...policy, max_lateness_minutes: Number(event.target.value) })
            }
          />
        </label>
        <label className="space-y-1 text-sm">
          {t("auditSchedule.notifications")}
          <select
            className="w-full rounded-md border border-input bg-background p-2"
            value={policy.notification_threshold ?? "warning"}
            onChange={(event) => {
              const value = event.target.value;
              if (
                value === "off" ||
                value === "info" ||
                value === "warning" ||
                value === "critical"
              )
                setPolicy({ ...policy, notification_threshold: value });
            }}
          >
            <option value="off">{t("auditSchedule.notifyOff")}</option>
            <option value="critical">{t("auditSchedule.notifyCritical")}</option>
            <option value="warning">{t("auditSchedule.notifyWarning")}</option>
            <option value="info">{t("auditSchedule.notifyInfo")}</option>
          </select>
        </label>
        <label className="space-y-1 text-sm">
          {t("auditSchedule.cooldown")}
          <Input
            type="number"
            min={0}
            max={1440}
            value={policy.notification_cooldown_minutes ?? 60}
            onChange={(event) =>
              setPolicy({ ...policy, notification_cooldown_minutes: Number(event.target.value) })
            }
          />
        </label>
        <label className="space-y-1 text-sm">
          {t("auditSchedule.timezone")}
          <Input
            value={policy.timezone}
            onChange={(event) => setPolicy({ ...policy, timezone: event.target.value })}
            required
          />
        </label>
        <label className="space-y-1 text-sm">
          {t("auditSchedule.windowStart")}
          <Input
            type="time"
            value={policy.start_time}
            onChange={(event) => setPolicy({ ...policy, start_time: event.target.value })}
            required
          />
        </label>
        <label className="space-y-1 text-sm">
          {t("auditSchedule.windowLength")}
          <Input
            type="number"
            min={1}
            max={1440}
            value={policy.window_minutes}
            onChange={(event) =>
              setPolicy({ ...policy, window_minutes: Number(event.target.value) })
            }
            required
          />
        </label>
        {policy.cadence === "weekly" ? (
          <label className="space-y-1 text-sm">
            {t("auditSchedule.weekday")}
            <Input
              type="number"
              min={0}
              max={6}
              value={policy.weekday}
              onChange={(event) => setPolicy({ ...policy, weekday: Number(event.target.value) })}
            />
          </label>
        ) : (
          <label className="space-y-1 text-sm">
            {t("auditSchedule.monthDay")}
            <Input
              type="number"
              min={1}
              max={31}
              value={policy.month_day}
              onChange={(event) => setPolicy({ ...policy, month_day: Number(event.target.value) })}
            />
          </label>
        )}
        <label className="space-y-1 text-sm">
          {t("auditSchedule.bandwidth")}
          <Input
            type="number"
            min={1024}
            max={1073741824}
            value={policy.bytes_per_second}
            onChange={(event) =>
              setPolicy({ ...policy, bytes_per_second: Number(event.target.value) })
            }
            required
          />
        </label>
      </div>
      <p className="text-xs text-muted-foreground">{t("auditSchedule.channelHelp")}</p>
      {policy.mode === "full" && (
        <label className="flex items-start gap-2 text-sm">
          <Checkbox
            checked={policy.full_cost_acknowledged}
            onChange={(full_cost_acknowledged) => setPolicy({ ...policy, full_cost_acknowledged })}
          />
          {t("auditSchedule.fullCost")}
        </label>
      )}
      <label className="flex items-center gap-2 text-sm">
        <Checkbox
          checked={policy.auto_repair}
          onChange={(auto_repair) => setPolicy({ ...policy, auto_repair })}
        />
        {t("auditSchedule.autoRepair")}
      </label>
      {policy.auto_repair && (
        <div className="flex flex-wrap gap-4 text-sm">
          {(["reparse_metadata", "regenerate_thumbnail"] as const).map((action) => (
            <label key={action} className="flex items-center gap-2">
              <Checkbox
                checked={policy.repair_actions.includes(action)}
                onChange={(checked) =>
                  setPolicy({
                    ...policy,
                    repair_actions: checked
                      ? [...policy.repair_actions, action]
                      : policy.repair_actions.filter((item) => item !== action),
                  })
                }
              />
              {action === "reparse_metadata"
                ? t("auditSchedule.metadata")
                : t("auditSchedule.thumbnails")}
            </label>
          ))}
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        {t("auditSchedule.nextDue")}: {shownDate(policy.next_due_at)} ·{" "}
        {t("auditSchedule.lastSuccess")}: {shownDate(policy.last_success_at)}
      </p>
      <p className="text-xs text-muted-foreground">
        {t("auditSchedule.estimatedReads")}: {formatBytes(policy.estimated_remote_bytes ?? 0)}
      </p>
      {policy.overdue && (
        <p role="status" className="text-sm text-warning">
          {t("auditSchedule.overdue")}
        </p>
      )}
      {policy.deferred_reason && (
        <p role="status" className="text-sm text-warning">
          {t("auditSchedule.deferred")}: {policy.deferred_reason.replaceAll("_", " ")}
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <Button type="submit" disabled={busy}>
          {t("auditSchedule.save")}
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={busy || !policy.next_due_at}
          onClick={() => void skip()}
        >
          {t("auditSchedule.skip")}
        </Button>
      </div>
    </form>
  );
}

export function AuditSchedulePanel() {
  const { t } = useI18n();
  const [policies, setPolicies] = useState<AuditPolicy[] | null>(null);
  const [history, setHistory] = useState<VaultAuditRun[]>([]);
  const [error, setError] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let cancelled = false;
    Promise.all([listAuditPolicies(), listVaultAudits()])
      .then(([nextPolicies, runs]) => {
        if (!cancelled) {
          setPolicies(nextPolicies);
          setHistory(runs);
          setError(false);
        }
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [revision]);
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("auditSchedule.title")}</CardTitle>
        <CardDescription>{t("auditSchedule.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        {error ? (
          <div role="alert">
            <p>{t("auditSchedule.loadFailed")}</p>
            <Button variant="outline" onClick={() => setRevision(revision + 1)}>
              {t("auditSchedule.retry")}
            </Button>
          </div>
        ) : !policies ? (
          <p role="status">{t("auditSchedule.loading")}</p>
        ) : (
          policies.map((policy) => (
            <PolicyForm
              key={`${policy.mode}-${policy.revision}`}
              initial={policy}
              onSaved={() => setRevision((value) => value + 1)}
            />
          ))
        )}
        <h4 className="border-t border-border pt-4 text-sm font-semibold">
          {t("auditSchedule.history")}
        </h4>
        {!history.length ? (
          <p className="mt-2 text-sm text-muted-foreground">{t("auditSchedule.empty")}</p>
        ) : (
          <ul className="divide-y divide-border">
            {history.map((run) => (
              <li key={run.id} className="flex flex-wrap justify-between gap-2 py-2 text-sm">
                <span>
                  #{run.id} · {run.mode} · {run.state} ·{" "}
                  {run.trigger === "scheduled"
                    ? t("auditSchedule.scheduled")
                    : t("auditSchedule.manual")}
                  {run.trigger === "scheduled" && (
                    <>
                      {" "}
                      ·{" "}
                      <a className="underline" href={`#audit-policy-${run.mode}`}>
                        {t("auditSchedule.schedule")}
                      </a>
                    </>
                  )}
                </span>
                <span className="text-muted-foreground">
                  {shownDate(run.finished_at ?? run.created_at)} · {run.critical_count}{" "}
                  {t("auditSchedule.critical")} · {run.warning_count} {t("auditSchedule.warnings")}
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
