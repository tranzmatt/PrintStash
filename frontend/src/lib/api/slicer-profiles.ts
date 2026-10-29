import { getJson, type GetJsonOptions } from "@/lib/api/request";
import type { ProfileSettingsKind, SlicerProfilePage } from "@/types/slicer-profiles";

export function listProfileSettings(
  kind: ProfileSettingsKind,
  profileId: number,
  beforeId: number | null,
  options?: GetJsonOptions,
): Promise<SlicerProfilePage> {
  const params = new URLSearchParams({ limit: "20" });
  if (beforeId !== null) params.set("before_id", String(beforeId));
  return getJson<SlicerProfilePage>(
    `/api/v1/slicer-profiles/${kind}/${profileId}?${params}`,
    options,
  );
}
