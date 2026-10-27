/** A real Orca upload makes its observed settings readable on desktop and mobile. */
import { readFileSync } from "node:fs";
import { test, expect } from "./helpers";
import { uploadModel } from "./util";

for (const width of [1440, 390]) {
  test(`inspects uploaded slicer settings at ${width}px`, async ({ page }, testInfo) => {
    // The shared upload helper follows Task Center in the desktop toolbar.
    // The reading flow below is exercised at the requested viewport.
    await page.setViewportSize({ width: 1440, height: 1000 });
    const name = `e2e-slicer-settings-${width}-${Date.now()}`;
    const filename = `${name}.gcode`;
    const source = readFileSync("../backend/tests/fixtures/real_orca_ender3_benchy.gcode");
    await uploadModel(page, name, {
      gcodeFile: {
        name: filename,
        mimeType: "text/plain",
        buffer: Buffer.concat([source, Buffer.from(`\n; fixture marker: ${name}\n`)]),
      },
    });
    let modelId = 0;
    await expect
      .poll(
        async () => {
          const result: { items: { filename: string; model_id: number }[] } = await (
            await page.request.get("/api/v1/slicer-profiles")
          ).json();
          const captured = result.items.find((item) => item.filename === filename);
          modelId = captured?.model_id ?? 0;
          return Boolean(captured);
        },
        { timeout: 60_000 },
      )
      .toBe(true);

    try {
      await page.setViewportSize({ width, height: 1000 });
      await page.goto("/profiles");
      await page.getByRole("tab", { name: "Detected settings", exact: true }).click();
      const entry = page.getByRole("article").filter({ hasText: filename });
      await entry.getByRole("button", { name: "View settings", exact: true }).click();
      await expect(entry.getByText("0.98", { exact: true })).toBeVisible();
      await entry.getByRole("tab", { name: "Printer settings", exact: true }).click();
      await expect(entry.getByText("nozzle_diameter", { exact: true })).toBeVisible();
      await entry.getByRole("tab", { name: "Process settings", exact: true }).click();
      await entry.getByRole("textbox", { name: "Find a setting or value" }).fill("layer_height");
      await expect(entry.getByText("0.2", { exact: true })).toBeVisible();
      await page.screenshot({ path: testInfo.outputPath("detected-settings.png"), fullPage: true });
      await entry.getByRole("link", { name: `Source: ${name}`, exact: true }).click();
      await expect(page).toHaveURL(new RegExp(`/models/${modelId}$`));
    } finally {
      await page.request.delete(`/api/v1/models/${modelId}`);
    }
  });
}
