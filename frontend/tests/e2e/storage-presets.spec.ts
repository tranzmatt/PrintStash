/** Named presets configure their existing transport through the shared form. */
import { expect, test } from "@playwright/test";
import { storageProviderCatalogue } from "../../src/test-support/storage-provider-catalogue";
import { aStorageConnection } from "../../src/test-support/factories";
import { useMockApi } from "./_setup";
useMockApi();
test.describe("storage presets", () => {
  for (const preset of [
    {
      id: "garage",
      fields: {
        Bucket: "models",
        Endpoint: "https://s3.example.test",
        "Access key": "test-access",
        "Secret key": "test-secret",
      },
      kind: "s3",
    },
    {
      id: "koofr",
      fields: { Username: "owner@example.test", Password: "app-password" },
      kind: "webdav",
    },
    {
      id: "hetzner_storage_box",
      fields: {
        Host: "box.example.test",
        Username: "owner",
        "Host key": "/run/known_hosts",
        Password: "test-password",
      },
      kind: "sftp",
    },
  ]) {
    test(`saves ${preset.id} through its declared role`, async ({ page }) => {
      await page.route("**/api/v1/storage/providers", (route) =>
        route.fulfill({ json: storageProviderCatalogue }),
      );
      await page.route("**/api/v1/storage-connections", (route) =>
        route.fulfill({
          json:
            route.request().method() === "POST"
              ? aStorageConnection({ name: "Preset backup" })
              : [],
          status: route.request().method() === "POST" ? 201 : 200,
        }),
      );
      await page.goto("/settings?section=remote-storage");
      await page.getByLabel("Provider").selectOption(preset.id);
      await page.getByLabel("Connection name").fill("Preset backup");
      await page.getByRole("combobox", { name: /Use for/ }).selectOption("backup");
      for (const [name, value] of Object.entries(preset.fields))
        await page.getByLabel(new RegExp(`^${name}(?:\\s*Optional)?$`)).fill(value);
      const saved = page.waitForRequest(
        (request) =>
          request.url().endsWith("/api/v1/storage-connections") && request.method() === "POST",
      );
      await page.getByRole("button", { name: "Save connection" }).click();
      expect((await saved).postDataJSON()).toMatchObject({
        kind: preset.kind,
        purpose: "backup",
        configuration: { provider: preset.id },
      });
      await expect(page.getByText("Preset backup", { exact: true })).toBeVisible();
    });
  }
});
