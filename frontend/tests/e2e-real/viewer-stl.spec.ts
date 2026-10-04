/** A refused viewer keeps its durable reason across page reloads and preserves originals. */
import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { test, expect } from "./helpers";

test.describe("viewer STL", () => {
  test("retains a memory refusal while keeping the original downloadable", async ({ page }) => {
    const name = `e2e-viewer-refused-${Date.now()}`;
    const backend = resolve("../backend");
    const original = execFileSync(
      resolve(backend, ".venv/bin/python"),
      [
        "-c",
        "import sys; from tests.factories.geometry import expanding_three_mf; sys.stdout.buffer.write(expanding_three_mf())",
      ],
      { cwd: backend },
    );
    const upload = await page.request.post("/api/v1/ingest/model", {
      multipart: {
        file: { name: `${name}.3mf`, mimeType: "model/3mf", buffer: original },
        model_name: name,
      },
    });
    expect(upload.status()).toBe(202);
    const jobId = (await upload.json()).job_id;
    let modelId = 0;
    let fileId = 0;
    await expect
      .poll(
        async () => {
          const job = await (await page.request.get(`/api/v1/jobs/${jobId}`)).json();
          modelId = job.model_id;
          fileId = job.file_id;
          return job.state;
        },
        { timeout: 60_000 },
      )
      .toBe("completed");
    try {
      await page.goto(`/models/${modelId}`);
      await expect(
        page.getByText("3D preview omitted due to memory limits", { exact: true }),
      ).toBeVisible({ timeout: 60_000 });
      const before = await (await page.request.get(`/api/v1/files/${fileId}/stl`)).json();
      expect(before.detail).toBe("resource_limit");

      await page.reload();

      await expect(
        page.getByText("3D preview omitted due to memory limits", { exact: true }),
      ).toBeVisible();
      const after = await (await page.request.get(`/api/v1/files/${fileId}/stl`)).json();
      expect(after).toEqual(before);
      const download = await page.request.get(`/api/v1/files/${fileId}/download`);
      expect(download.status()).toBe(200);
      expect(await download.body()).toEqual(original);
    } finally {
      await page.request.delete(`/api/v1/models/${modelId}`);
    }
  });
  test("shares concurrent viewer preparation", async ({ page }) => {
    const name = `e2e-viewer-concurrent-${Date.now()}`;
    const backend = resolve("../backend");
    const payload = execFileSync(
      resolve(backend, ".venv/bin/python"),
      [
        "-c",
        "import sys; from tests.factories.geometry import three_mf; sys.stdout.buffer.write(three_mf())",
      ],
      { cwd: backend },
    );
    const upload = await page.request.post("/api/v1/ingest/model", {
      multipart: {
        file: { name: `${name}.3mf`, mimeType: "model/3mf", buffer: payload },
        model_name: name,
      },
    });
    expect(upload.status()).toBe(202);
    const jobId = (await upload.json()).job_id;
    let modelId = 0;
    let fileId = 0;
    await expect
      .poll(
        async () => {
          const job = await (await page.request.get(`/api/v1/jobs/${jobId}`)).json();
          modelId = job.model_id;
          fileId = job.file_id;
          return job.state;
        },
        { timeout: 60_000 },
      )
      .toBe("completed");
    try {
      const jobsUrl =
        "/api/v1/jobs?include_system=true&kind=derivatives.viewer_stl&terminal_limit=100";
      const previousJobs = await (await page.request.get(jobsUrl)).json();
      const previousIds = new Set(previousJobs.map((job: { job_id: string }) => job.job_id));
      const responses = await Promise.all(
        Array.from({ length: 4 }, () => page.request.get(`/api/v1/files/${fileId}/stl`)),
      );
      expect(responses.every((response) => [200, 202].includes(response.status()))).toBe(true);
      await expect
        .poll(async () => (await page.request.get(`/api/v1/files/${fileId}/stl`)).status(), {
          timeout: 60_000,
        })
        .toBe(200);
      await page.goto(`/models/${modelId}`);
      await expect(page.getByRole("button", { name: "Screenshot", exact: true })).toBeEnabled({
        timeout: 60_000,
      });
      await expect(page.locator("canvas")).toBeVisible();
      const jobs = await (await page.request.get(jobsUrl)).json();
      const previews = jobs.filter((job: { job_id: string }) => !previousIds.has(job.job_id));
      expect(previews).toHaveLength(1);
      expect(previews[0].attempts).toBe(1);
    } finally {
      await page.request.delete(`/api/v1/models/${modelId}`);
    }
  });
});
