import { getJson } from "@/lib/api/request";
import type { FilePlates } from "@/types";

/** A 3MF Artifact's plates, as its `plates` derivative laid them out. */
export function getFilePlates(fileId: number, signal?: AbortSignal): Promise<FilePlates> {
  return getJson<FilePlates>(`/api/v1/files/${fileId}/plates`, { signal });
}
