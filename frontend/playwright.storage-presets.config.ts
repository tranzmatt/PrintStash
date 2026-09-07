import { defineConfig } from "@playwright/test";
import storageConfig from "./playwright.storage.config";

// Reuse the real WebDAV harness; the shared auth fixture targets this API.
process.env.PLAYWRIGHT_REAL_API_PORT = process.env.PLAYWRIGHT_STORAGE_API_PORT ?? "8420";

export default defineConfig({
  ...storageConfig,
  testDir: "./tests/e2e-real/storage-presets",
});
