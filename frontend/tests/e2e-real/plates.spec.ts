/**
 * A multi-plate slicer project shows one plate at a time, as the slicer lays it out.
 *
 * The plates are derived in the background after the upload; the model page
 * then offers each plate by the slicer's number and name, and choosing one
 * shows only that plate's parts in the 3D view.
 */
import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { test, expect } from "./helpers";

test.describe("3MF plates", () => {
  test("shows one plate of a multi-plate project", async ({ page }) => {
    const name = `e2e-plates-${Date.now()}`;
    const backend = resolve("../backend");
    const project = execFileSync(
      resolve(backend, ".venv/bin/python"),
      [
        "-c",
        "import sys; from tests.fixtures.three_mf_projects import build_multi_plate_project; sys.stdout.buffer.write(build_multi_plate_project(marker=sys.argv[1]))",
        name,
      ],
      { cwd: backend },
    );
    const upload = await page.request.post("/api/v1/ingest/model", {
      multipart: {
        file: { name: `${name}.3mf`, mimeType: "model/3mf", buffer: project },
        model_name: name,
      },
    });
    expect(upload.status()).toBe(202);
    const jobId = (await upload.json()).job_id;
    let modelId = 0;
    await expect
      .poll(
        async () => {
          const job = await (await page.request.get(`/api/v1/jobs/${jobId}`)).json();
          modelId = job.model_id;
          return job.state;
        },
        { timeout: 60_000 },
      )
      .toBe("completed");
    try {
      await page.goto(`/models/${modelId}`);
      const plates = page.getByRole("group", { name: "Plates" });
      await expect(plates).toBeVisible({ timeout: 60_000 });
      await expect(page.getByRole("button", { name: "Screenshot", exact: true })).toBeEnabled({
        timeout: 60_000,
      });
      await expect(page.getByText(/^[\d.]+×[\d.]+×[\d.]+ mm$/)).toBeVisible({ timeout: 60_000 });

      await plates.getByRole("button", { name: /Plate 02.*Wall mount/ }).click();

      await expect(plates.getByRole("button", { name: /Plate 02/ })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
      await expect(page.getByText(/Viewing: .*· Plate 02/)).toBeVisible();
      await expect(page.locator("canvas")).toBeVisible();
      await expect(page.getByText("Nothing is placed on this plate")).toHaveCount(0);
      // The Model's dimensions measure the whole build, not the plate on screen.
      await expect(page.getByText(/^[\d.]+×[\d.]+×[\d.]+ mm$/)).toHaveCount(0);
    } finally {
      expect((await page.request.delete(`/api/v1/models/${modelId}`)).status()).toBe(204);
    }
  });
});
