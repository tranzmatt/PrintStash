import { infiniteQueryOptions } from "@tanstack/react-query";
import { listProfileSettings } from "@/lib/api/slicer-profiles";
import type { ProfileSettingsKind } from "@/types/slicer-profiles";

export const slicerProfileKeys = {
  all: ["slicer-profiles"] as const,
  profile: (kind: ProfileSettingsKind, id: number, epoch: string, version: number) =>
    ["slicer-profiles", kind, id, epoch, version] as const,
};

export function profileSettingsOptions(
  kind: ProfileSettingsKind,
  id: number,
  epoch: string,
  version: number,
) {
  return infiniteQueryOptions({
    queryKey: slicerProfileKeys.profile(kind, id, epoch, version),
    // SAFETY: the initial cursor is absent; subsequent API pages return a numeric file ID.
    initialPageParam: null as number | null,
    queryFn: ({ signal, pageParam }) => listProfileSettings(kind, id, pageParam, { signal }),
    getNextPageParam: (page) => page.next_before_id,
  });
}
