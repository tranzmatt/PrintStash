/** Create a set from models selected across folders in the shared ZIP-style browser. */
import type { CollectionRead, MultipartModelRead } from "../../src/types";
import { test, expect } from "./helpers";
import { uploadModel } from "./util";

for (const width of [1440, 390]) {
  test(`creates a multipart set from browsed models at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    const stamp = `${width}-${Date.now()}`;
    const parentName = `workshop-archives-printed-replacement-parts-${stamp}`;
    const childName = `adjustable-brackets-reinforced-mounting-points-${stamp}`;
    const parentResponse = await page.request.post("/api/v1/collections", {
      data: { name: parentName },
    });
    expect(parentResponse.ok()).toBe(true);
    const parent: CollectionRead = await parentResponse.json();
    const childResponse = await page.request.post("/api/v1/collections", {
      data: { name: childName, parent_id: parent.id },
    });
    expect(childResponse.ok()).toBe(true);
    const child: CollectionRead = await childResponse.json();
    const baseName = "Bracket base " + stamp;
    const lidName = "Bracket cover " + stamp;
    await uploadModel(page, baseName, { collection: parent.path });
    await uploadModel(page, lidName, { collection: child.path });
    await page.setViewportSize({ width, height: 1000 });
    await page.emulateMedia({ reducedMotion: width < 640 ? "reduce" : "no-preference" });

    await page.goto("/");
    if (width < 640) {
      await page.getByRole("main").getByRole("button", { name: "More", exact: true }).click();
      await page.getByRole("menuitem", { name: "New multipart set" }).click();
    } else {
      await page.getByRole("button", { name: "New multipart set" }).first().click();
    }
    const modal = page.getByRole("dialog", { name: "New multipart set", exact: true });
    await modal.getByLabel("Name", { exact: true }).fill(`Bracket assembly ${stamp}`);
    await page.screenshot({
      path: testInfo.outputPath("multipart-folder-unchecked.png"),
      fullPage: true,
    });
    await modal.getByRole("button", { name: "Select folder " + parentName, exact: true }).click();
    await expect(modal.getByRole("status")).toHaveText("2 selected");
    await expect(
      modal.getByRole("button", { name: "Deselect folder " + parentName, exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
    await page.screenshot({
      path: testInfo.outputPath("multipart-folder-checked.png"),
      fullPage: true,
    });
    await modal.getByRole("button", { name: "Deselect folder " + parentName, exact: true }).click();
    await expect(modal.getByRole("status")).toHaveText("0 selected");
    await modal.getByRole("button", { name: "Select folder " + parentName, exact: true }).click();
    await expect(modal.getByRole("status")).toHaveText("2 selected");
    const viewport = modal.locator("[data-selection-viewport]");
    const beforeNavigation = await modal.boundingBox();
    const beforeViewport = await viewport.boundingBox();
    const pendingModels = Promise.withResolvers<void>();
    await page.route("**/api/v1/models/page?**", async (route) => {
      const params = new URL(route.request().url()).searchParams;
      if (params.get("collection") === parent.path) await pendingModels.promise;
      await route.continue();
    });
    await modal.getByRole("button", { name: "Open folder " + parentName, exact: true }).click();
    await expect(viewport).toHaveAttribute("aria-busy", "true");
    expect(
      Math.abs((await modal.boundingBox())!.height - beforeNavigation!.height),
    ).toBeLessThanOrEqual(1);
    expect(
      Math.abs((await viewport.boundingBox())!.height - beforeViewport!.height),
    ).toBeLessThanOrEqual(1);
    await expect(
      modal.getByRole("button", { name: "Open folder " + childName, exact: true }),
    ).toHaveCount(0);
    pendingModels.resolve();
    await expect(viewport).toHaveAttribute("aria-busy", "false");
    await expect(viewport.locator(":scope > div")).toHaveCSS(
      "animation-name",
      width < 640 ? "fade-in" : "folder-in-forward",
    );
    expect(
      Math.abs((await modal.boundingBox())!.height - beforeNavigation!.height),
    ).toBeLessThanOrEqual(1);
    await page.unroute("**/api/v1/models/page?**");
    await expect(modal.getByRole("button", { name: baseName, exact: true })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await page.screenshot({
      path: testInfo.outputPath("multipart-browser-folders.png"),
      fullPage: true,
    });
    await modal.getByRole("button", { name: "Open folder " + childName, exact: true }).click();
    await expect(modal.getByRole("button", { name: lidName, exact: true })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await expect(modal.getByRole("status")).toHaveText("2 selected");
    await modal.getByRole("textbox", { name: "Search existing models" }).fill(baseName);
    await expect(modal.getByRole("button", { name: baseName, exact: true })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await page.screenshot({
      path: testInfo.outputPath("multipart-browser-selected.png"),
      fullPage: true,
    });

    await expect(page.getByRole("textbox", { name: "Find destination" })).toHaveCount(0);
    const trigger = modal.getByRole("button", { name: "Collection", exact: true });
    await trigger.click();
    const picker = page.getByRole("dialog", { name: "Collection", exact: true });
    const search = picker.getByRole("textbox", { name: "Find destination" });
    await expect(search).toBeFocused();
    await search.fill(stamp);
    const option = picker.getByRole("option", {
      name: `${parentName}/${childName} (1)`,
      exact: true,
    });
    await expect(option.getByText(childName, { exact: true })).toBeVisible();
    await expect(option.getByText(`${parentName}/${childName}`, { exact: true })).toBeVisible();
    expect(
      await picker.evaluate((element) => element.scrollWidth - element.clientWidth),
    ).toBeLessThanOrEqual(1);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      ),
    ).toBeLessThanOrEqual(1);
    await page.screenshot({
      path: testInfo.outputPath("multipart-destination.png"),
      fullPage: true,
    });
    await search.press("Escape");
    await expect(picker).toHaveCount(0);
    await expect(trigger).toBeFocused();
    await expect(modal.getByLabel("Name", { exact: true })).toHaveValue(
      `Bracket assembly ${stamp}`,
    );
    await trigger.click();
    await picker.getByRole("textbox", { name: "Find destination" }).fill(stamp);
    await option.click();
    await expect(trigger).toContainText(childName);
    await expect(picker).toHaveCount(0);

    const saving = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/v1/multipart-models" &&
        response.request().method() === "POST",
    );
    await modal.getByRole("button", { name: "Create multipart set" }).click();
    const response = await saving;
    expect(response.ok(), await response.text()).toBe(true);
    const created: MultipartModelRead = await response.json();
    expect(created.collection_id).toBe(child.id);
    expect(created.parts.map((part) => part.models[0]?.name)).toEqual([baseName, lidName]);
    const persisted = await page.request.get(`/api/v1/multipart-models/${created.id}`);
    const saved: MultipartModelRead = await persisted.json();
    expect(saved.collection_id).toBe(child.id);
    expect(saved.part_count).toBe(2);
    await expect(page.getByRole("heading", { name: `Bracket assembly ${stamp}` })).toBeVisible();
  });
}
