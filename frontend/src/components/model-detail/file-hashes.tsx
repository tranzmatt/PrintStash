import { useI18n } from "@/lib/i18n";
import type { FileRead } from "@/types";

export function FileHashes({ files }: { files: FileRead[] }) {
  const { t } = useI18n();
  if (files.length === 0) return null;
  return (
    <section
      aria-label={t("modelHashes.title")}
      className="space-y-3 border-t border-outline-variant pt-4"
    >
      <h3 className="text-sm font-medium text-on-surface">{t("modelHashes.title")}</h3>
      <div className="divide-y divide-outline-variant">
        {files.map((file) => (
          <div key={file.id} className="min-w-0 space-y-2 py-3 first:pt-0 last:pb-0">
            <p className="break-words text-sm text-on-surface">{file.original_filename}</p>
            <dl className="space-y-2">
              <div>
                <dt className="text-xs text-on-surface-variant">{t("modelHashes.file")}</dt>
                <dd className="select-all break-all font-mono text-xs leading-relaxed text-on-surface">
                  {file.sha256}
                </dd>
              </div>
              {file.geometric_sha256 !== null && (
                <div>
                  <dt
                    className="text-xs text-on-surface-variant"
                    title={t("modelHashes.geometryHelp")}
                  >
                    {t("modelHashes.geometry")}
                  </dt>
                  <dd className="select-all break-all font-mono text-xs leading-relaxed text-on-surface">
                    {file.geometric_sha256}
                  </dd>
                </div>
              )}
            </dl>
          </div>
        ))}
      </div>
    </section>
  );
}
