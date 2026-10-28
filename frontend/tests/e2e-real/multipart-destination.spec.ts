/** Search a nested destination using the shared ZIP picker, then persist the chosen folder. */
import type { CollectionRead, MultipartModelRead } from "../../src/types";
import { test, expect } from "./helpers";

for (const width of [1440, 390]) {
  test(`finds a multipart destination at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    const stamp = `${width}-${Date.now()}`;
    const parentName = `Workshop archives - printed replacement parts - ${stamp}`;
    const childName = `Adjustable brackets with reinforced mounting points - ${stamp}`;
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

    await page.goto("/");
    if (width < 640) {
      await page.getByRole("main").getByRole("button", { name: "More", exact: true }).click();
      await page.getByRole("menuitem", { name: "New multipart set" }).click();
    } else {
      await page.getByRole("button", { name: "New multipart set" }).first().click();
    }
    const modal = page.getByRole("dialog", { name: "New multipart set", exact: true });
    await modal.getByLabel("Name", { exact: true }).fill(`Bracket assembly ${stamp}`);
    await expect(page.getByRole("textbox", { name: "Find destination" })).toHaveCount(0);
    const trigger = modal.getByRole("button", { name: "Collection", exact: true });
    await trigger.click();
    const picker = page.getByRole("dialog", { name: "Collection", exact: true });
    const search = picker.getByRole("textbox", { name: "Find destination" });
    await expect(search).toBeFocused();
    await search.fill(stamp);
    const option = picker.getByRole("option", {
      name: `${parentName}/${childName} (0)`,
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
    const persisted = await page.request.get(`/api/v1/multipart-models/${created.id}`);
    expect((await persisted.json()).collection_id).toBe(child.id);
    await expect(page.getByRole("heading", { name: `Bracket assembly ${stamp}` })).toBeVisible();
  });
}
