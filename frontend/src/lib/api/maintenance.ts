import { getJson, sendJson } from "@/lib/api/request";
import type {
  AuditPolicy,
  BackupVerification,
  VaultAuditFinding,
  VaultAuditMode,
  VaultAuditRun,
} from "@/types/maintenance";

export function startVaultAudit(mode: VaultAuditMode): Promise<VaultAuditRun> {
  return sendJson<VaultAuditRun>("/api/v1/maintenance/audits", "POST", { mode });
}

export function getLatestVaultAudit(): Promise<VaultAuditRun> {
  return getJson<VaultAuditRun>("/api/v1/maintenance/audits/latest", { fresh: true });
}

export function getVaultAudit(id: number): Promise<VaultAuditRun> {
  return getJson<VaultAuditRun>(`/api/v1/maintenance/audits/${id}`, { fresh: true });
}

export function cancelVaultAudit(id: number): Promise<VaultAuditRun> {
  return sendJson<VaultAuditRun>(`/api/v1/maintenance/audits/${id}/cancel`, "POST", {});
}

export function repairAuditFinding(id: number): Promise<VaultAuditFinding> {
  return sendJson<VaultAuditFinding>(`/api/v1/maintenance/findings/${id}/repair`, "POST", {});
}

export function ignoreAuditFinding(id: number): Promise<VaultAuditFinding> {
  return sendJson<VaultAuditFinding>(`/api/v1/maintenance/findings/${id}/ignore`, "POST", {});
}

export function verifyBackup(
  backupId: string,
  sourceRef?: string | null,
): Promise<BackupVerification> {
  const query = sourceRef ? `?source_ref=${encodeURIComponent(sourceRef)}` : "";
  return sendJson<BackupVerification>(
    `/api/v1/backups/${encodeURIComponent(backupId)}/verify${query}`,
    "POST",
    {},
  );
}

export function listAuditPolicies(): Promise<AuditPolicy[]> {
  return getJson<AuditPolicy[]>("/api/v1/maintenance/audit-policies", { fresh: true });
}

export function saveAuditPolicy(policy: AuditPolicy): Promise<AuditPolicy> {
  const {
    mode,
    revision: _revision,
    next_due_at: _next,
    last_attempt_at: _attempt,
    last_success_at: _success,
    deferred_reason: _reason,
    ...payload
  } = policy;
  return sendJson<AuditPolicy>(`/api/v1/maintenance/audit-policies/${mode}`, "PUT", payload);
}

export function skipAuditSlot(mode: VaultAuditMode): Promise<AuditPolicy> {
  return sendJson<AuditPolicy>(`/api/v1/maintenance/audit-policies/${mode}/skip`, "POST", {});
}

export function listVaultAudits(): Promise<VaultAuditRun[]> {
  return getJson<VaultAuditRun[]>("/api/v1/maintenance/audits", { fresh: true });
}
