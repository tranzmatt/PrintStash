import { getJson, sendJson } from "./request";

export interface StorageInventory {
  generated_at: string;
  measured_at: string | null;
  target_ref: string;
  logical_bytes: number;
  external_referenced_bytes: number;
  unique_owned_bytes: number;
  unknown_object_count: number;
  temporary_bytes: number;
  backup_bytes: number;
  measured_provider_bytes: number | null;
  method: string;
  confidence: string;
  buckets: {
    category: string;
    lifecycle: string;
    count: number;
    logical_bytes: number;
    external_bytes: number;
  }[];
  volumes: {
    domain_id: string;
    roles: string[];
    total_bytes: number | null;
    free_bytes: number | null;
    reserved_bytes: number;
    headroom_bytes: number;
    status: string;
    method: string;
  }[];
}

export interface StorageInventoryReport {
  inventory: StorageInventory;
  history: { sampled_at: string; owned_bytes: number }[];
  forecast: { status: string; days_remaining: number | null; bytes_per_day: number | null };
}

export const getStorageInventory = () =>
  getJson<StorageInventoryReport>("/api/v1/storage/inventory", { fresh: true });
export const sampleStorageInventory = () =>
  sendJson<StorageInventory>("/api/v1/storage/inventory/sample", "POST", {});
export const cleanupStorageStaging = () =>
  sendJson<{ leases_removed: number; files_removed: number }>(
    "/api/v1/storage/inventory/cleanup-staging",
    "POST",
    {},
  );
