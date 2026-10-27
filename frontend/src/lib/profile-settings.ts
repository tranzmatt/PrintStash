import type { ProfileSettingsKind, SlicerProfileRead } from "@/types/slicer-profiles";

export interface SettingsVariant {
  key: string;
  settings: Record<string, string>;
  sources: SlicerProfileRead[];
}

function ordered(settings: Record<string, string>) {
  return Object.entries(settings).sort(([a], [b]) => a.localeCompare(b));
}

/** Group observations, never infer a single authoritative preset from them. */
export function groupProfileSettings(
  kind: ProfileSettingsKind,
  captures: SlicerProfileRead[],
): SettingsVariant[] {
  const groups = new Map<string, SettingsVariant>();
  const seen = new Set<number>();
  for (const source of captures) {
    if (seen.has(source.file_id)) continue;
    seen.add(source.file_id);
    const settings = source.settings[kind];
    if (Object.keys(settings).length === 0) continue;
    const key = JSON.stringify([
      source.slicer_name,
      source.slicer_version,
      source.printer_model,
      // Unknown provenance must not accidentally merge unrelated presets.
      source.slicer_name === null || source.printer_model === null ? source.file_id : null,
      kind === "filament" ? ordered(source.settings.printer) : null,
      ordered(settings),
    ]);
    const existing = groups.get(key);
    if (existing) existing.sources.push(source);
    else groups.set(key, { key, settings, sources: [source] });
  }
  return [...groups.values()];
}
