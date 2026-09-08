import { useOptionalI18n, type MessageKey } from "@/lib/i18n";
import { uiText } from "@/lib/locale";
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
      <p>{i18n?.t("storage.preset.evidence") ?? uiText("storage.preset.evidence")}</p>
      {provider.delivery?.signed_get && (
        <p>{i18n?.t("storage.preset.delivery") ?? uiText("storage.preset.delivery")}</p>
      )}
      {provider.provider_documentation_url && (
        <a
          className="text-primary underline underline-offset-2 focus-visible:ring-2 focus-visible:ring-ring"
          href={provider.provider_documentation_url}
          target="_blank"
          rel="noreferrer"
        >
          {i18n?.t("storage.preset.instructions") ?? uiText("storage.preset.instructions")}
        </a>
      )}
    </div>
  );
}
