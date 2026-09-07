import "@testing-library/jest-dom/vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { StorageInventoryPanel } from "@/components/storage-inventory-panel";
import { adminSession, json, renderApp } from "@/test-support/render";
import type { StorageInventoryReport } from "@/lib/api/storage-inventory";

const report: StorageInventoryReport = {
  inventory: {
    generated_at: "2026-09-07T00:00:00Z",
    measured_at: null,
    target_ref: "test",
    logical_bytes: 0,
    external_referenced_bytes: 0,
    unique_owned_bytes: 0,
    unknown_object_count: 2,
    temporary_bytes: 0,
    backup_bytes: 0,
    measured_provider_bytes: null,
    method: "database ownership census",
    confidence: "known sizes only",
    buckets: [],
    volumes: [
      {
        domain_id: "test",
        roles: ["vault"],
        total_bytes: null,
        free_bytes: null,
        reserved_bytes: 0,
        headroom_bytes: 0,
        status: "unknown",
        method: "unavailable",
      },
    ],
  },
  history: [],
  forecast: { status: "insufficient_data", days_remaining: null, bytes_per_day: null },
};

function setup(response = report) {
  return renderApp(<StorageInventoryPanel />, {
    auth: adminSession(),
    routes: { "GET /api/v1/storage/inventory": () => json(response) },
  });
}

describe("Storage insights", () => {
  it("explains unknown capacity", async () => {
    setup();
    expect(await screen.findByText("Capacity unknown")).toBeVisible();
    expect(screen.getByText(/2 objects have no recorded size/)).toBeVisible();
  });
  it("explains allocation blockers", async () => {
    setup({
      ...report,
      inventory: {
        ...report.inventory,
        volumes: [{ ...report.inventory.volumes[0], status: "blocked", free_bytes: 0 }],
      },
    });
    expect(await screen.findByText("New allocations blocked")).toBeVisible();
  });
  it("plots persisted history", async () => {
    setup({
      ...report,
      history: [
        { sampled_at: "2026-09-01T00:00:00Z", owned_bytes: 40 },
        { sampled_at: "2026-09-07T00:00:00Z", owned_bytes: 80 },
      ],
    });
    expect(
      await screen.findByRole("img", { name: "Recorded owned storage over time" }),
    ).toBeVisible();
  });
  it("requires confirmation for staging cleanup", async () => {
    setup();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Clean up expired staging" }));
    expect(await screen.findByRole("dialog")).toHaveTextContent("Uncertain files are retained");
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});
