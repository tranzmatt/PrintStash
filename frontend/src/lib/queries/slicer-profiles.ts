import { queryOptions } from "@tanstack/react-query";
import { listSlicerProfiles } from "@/lib/api/slicer-profiles";

export const slicerProfileKeys = {
  all: ["slicer-profiles"] as const,
  page: (beforeId: number | null) => ["slicer-profiles", beforeId] as const,
};

export function slicerProfilesOptions(beforeId: number | null) {
  return queryOptions({
    queryKey: slicerProfileKeys.page(beforeId),
    queryFn: ({ signal }) => listSlicerProfiles(beforeId, { signal }),
  });
}
