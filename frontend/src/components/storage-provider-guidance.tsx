import { useOptionalI18n, type MessageKey } from "@/lib/i18n";
import type { StorageProvider } from "@/types";

const GUIDANCE_KEYS = {
  synology: "storage.preset.mounted",
  truenas: "storage.preset.mounted",
  qnap: "storage.preset.mounted",
  unraid: "storage.preset.mounted",
  synology_webdav: "storage.preset.synology",
  qnap_webdav: "storage.preset.qnap",
  minio: "storage.preset.minio",
  garage: "storage.preset.garage",
  seaweedfs: "storage.preset.seaweedfs",
  hetzner_object_storage: "storage.preset.hetznerObject",
  hetzner_storage_box: "storage.preset.hetznerSftp",
  hetzner_storage_box_webdav: "storage.preset.hetznerWebdav",
  koofr: "storage.preset.koofr",
} satisfies Record<string, MessageKey>;

export function StorageProviderGuidance({ provider }: { provider: StorageProvider }) {
  const i18n = useOptionalI18n();
  if (!provider.setup_guidance) return null;
  const key = Object.entries(GUIDANCE_KEYS).find(([id]) => id === provider.id)?.[1];
  return (
    <div className="space-y-2 text-xs text-muted-foreground sm:col-span-2">
      <p>{i18n && key ? i18n.t(key) : provider.setup_guidance}</p>
      <p>
        {i18n?.t("storage.preset.evidence") ??
          "Transport tested. Validate your endpoint; appliance hardware and hosted accounts are not certified."}
      </p>
      {provider.delivery?.signed_get && (
        <p>
          {i18n?.t("storage.preset.delivery") ??
            "Direct downloads require endpoint and browser CORS checks. Same-origin downloads remain available. Download support does not grant deletion permission."}
        </p>
      )}
      {provider.provider_documentation_url && (
        <a
          className="text-primary underline underline-offset-2 focus-visible:ring-2 focus-visible:ring-ring"
          href={provider.provider_documentation_url}
          target="_blank"
          rel="noreferrer"
        >
          {i18n?.t("storage.preset.instructions") ?? "Provider setup instructions"}
        </a>
      )}
    </div>
  );
}
