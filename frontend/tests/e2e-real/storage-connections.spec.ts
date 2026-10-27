/** Reusable storage edits preserve deliberate intent across competing administrators. */
import { createServer } from "node:http";
import { test, expect } from "./helpers";
import type { StorageConnection } from "../../src/types";

const API = `http://127.0.0.1:${process.env.PLAYWRIGHT_REAL_API_PORT ?? 8410}`;

test.describe("storage connection editing", () => {
  test("resolves competing connection editors", async ({ page, context }) => {
    const name = `connection-${Date.now()}`;
    const created = await page.request.post(`${API}/api/v1/storage-connections`, {
      data: {
        name,
        kind: "s3",
        purpose: "both",
        configuration: { bucket: "unused-e2e-bucket", root: "PrintStash" },
        secrets: { access_key: "FakeBrowserAccessKey", secret_key: "FakeBrowserSecretKey" },
      },
    });
    expect(created.status()).toBe(201);
    const connection: StorageConnection = await created.json();
    const second = await context.newPage();
    try {
      await page.goto("/settings?section=remote-storage");
      await second.goto("/settings?section=remote-storage");
      await page.getByRole("button", { name: "Edit", exact: true }).click();
      await second.getByRole("button", { name: "Edit", exact: true }).click();
      await page.getByLabel("Connection name", { exact: true }).fill(`${name}-winner`);
      await page.getByRole("button", { name: "Backup replicas", exact: true }).click();
      await second.getByLabel("Connection name", { exact: true }).fill(`${name}-revised`);
      const path = `/api/v1/storage-connections/${connection.id}`;
      const accepted = page.waitForResponse(
        (response) => response.url().endsWith(path) && response.request().method() === "PATCH",
      );
      await page.getByRole("button", { name: "Save changes", exact: true }).click();
      expect((await accepted).status()).toBe(200);
      const conflict = second.waitForResponse(
        (response) => response.url().endsWith(path) && response.request().method() === "PATCH",
      );
      await second.getByRole("button", { name: "Save changes", exact: true }).click();
      expect((await conflict).status()).toBe(412);
      await expect(second.getByLabel("Connection name", { exact: true })).toHaveValue(
        `${name}-revised`,
      );
      await expect(
        second.getByRole("button", { name: "Save changes", exact: true }),
      ).toBeDisabled();
      await second.getByRole("button", { name: "Review current values" }).click();
      await expect(
        second.getByRole("region", { name: "Latest saved version" }).getByText(`${name}-winner`),
      ).toBeVisible();
      const revised = second.waitForResponse(
        (response) => response.url().endsWith(path) && response.request().method() === "PATCH",
      );
      await second.getByRole("button", { name: "Save revised changes" }).click();
      expect((await revised).status()).toBe(200);
      await expect(second.getByRole("combobox", { name: `Use ${name}-revised for` })).toHaveValue(
        "backup",
      );
      const rows: StorageConnection[] = await (
        await page.request.get(`${API}/api/v1/storage-connections`)
      ).json();
      expect(rows.find((row) => row.id === connection.id)).toMatchObject({
        name: `${name}-revised`,
        purpose: "backup",
        secret_fields_set: ["access_key", "secret_key"],
      });
    } finally {
      await second.close();
      await page.request.delete(`${API}/api/v1/storage-connections/${connection.id}`);
    }
  });
});

test.describe("storage connection access warnings", () => {
  test("reports expired storage credentials without signing out", async ({ page }) => {
    let expired = true;
    const server = createServer((request, response) => {
      const url = new URL(request.url!, "http://127.0.0.1");
      if (
        request.method !== "GET" ||
        url.searchParams.get("list-type") !== "2" ||
        !request.headers.authorization?.includes("FakeBrowserAccessKey")
      ) {
        response.writeHead(400).end();
        return;
      }
      const body = expired
        ? "<Error><Code>ExpiredToken</Code><Message>The provided token has expired.</Message></Error>"
        : '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Name>fixture-bucket</Name><Prefix>models/</Prefix><KeyCount>0</KeyCount><MaxKeys>1000</MaxKeys><IsTruncated>false</IsTruncated></ListBucketResult>';
      response
        .writeHead(expired ? 400 : 200, {
          "Content-Type": "application/xml",
          "Content-Length": Buffer.byteLength(body),
        })
        .end(body);
    });
    await new Promise<void>((resolve, reject) => {
      server.once("error", reject);
      server.listen(0, "127.0.0.1", resolve);
    });
    const address = server.address();
    // oxlint-disable-next-line anti-slop/no-runtime-typeof -- Node socket addresses are a TCP/pipe/null union at this I/O boundary.
    if (address === null || typeof address === "string")
      throw new Error("Missing S3 fixture address");
    let connectionId: number | null = null;
    const name = `expired-storage-${Date.now()}`;
    try {
      const created = await page.request.post(`${API}/api/v1/storage-connections`, {
        data: {
          name,
          kind: "s3",
          purpose: "library",
          configuration: {
            provider: "s3_self_hosted",
            bucket: "fixture-bucket",
            root: "models",
            endpoint_url: `http://127.0.0.1:${address.port}`,
            region: "us-east-1",
            addressing_style: "path",
          },
          secrets: { access_key: "FakeBrowserAccessKey", secret_key: "FakeBrowserSecretKey" },
        },
      });
      expect(created.status()).toBe(201);
      const connection: StorageConnection = await created.json();
      connectionId = connection.id;
      await page.goto("/settings?section=remote-storage");
      const row = page.getByRole("listitem").filter({ has: page.getByText(name, { exact: true }) });
      const rejected = page.waitForResponse((response) =>
        response.url().endsWith(`/storage-connections/${connection.id}/probe`),
      );
      await row.getByRole("button", { name: "Test", exact: true }).click();
      expect((await rejected).status()).toBe(409);
      await expect(row.getByRole("alert")).toContainText("credentials have expired");
      expect((await page.request.get(`${API}/api/v1/auth/me`)).status()).toBe(200);
      expired = false;
      await row.getByRole("button", { name: "Test", exact: true }).click();
      await expect(page.getByText(`${name} is reachable.`, { exact: true })).toBeVisible();
      await expect(row.getByRole("alert")).toHaveCount(0);
    } finally {
      if (connectionId !== null) {
        await page.request.delete(`${API}/api/v1/storage-connections/${connectionId}`);
      }
      server.closeAllConnections();
      await new Promise<void>((resolve, reject) =>
        server.close((error) => (error ? reject(error) : resolve())),
      );
    }
  });
});
