/** Captured print settings remain read-only evidence tied to their source file. */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { SlicerProfileDetails } from "@/components/slicer-profile-details";
import { slicerProfileKeys } from "@/lib/queries/slicer-profiles";
import { json, renderApp } from "@/test-support/render";
import type { SlicerProfileRead } from "@/types/slicer-profiles";

const profile: SlicerProfileRead = {
  file_id: 10,
  model_id: 4,
  model_name: "Bracket",
  filename: "bracket.gcode",
  uploaded_at: "2026-10-27T10:00:00Z",
  slicer_name: "OrcaSlicer",
  slicer_version: "2.3.2",
  settings: {
    printer: { nozzle_diameter: "0.4" },
    filament: { filament_flow_ratio: "0.98;1.02", filament_type: "PLA" },
    process: { layer_height: "0.2" },
  },
};

describe("SlicerProfileDetails", () => {
  it("shows the source model link", async () => {
    renderApp(<SlicerProfileDetails />, {
      seed: [[slicerProfileKeys.page(null), { items: [profile], next_before_id: null }]],
    });

    expect(await screen.findByRole("link", { name: "Source: Bracket" })).toHaveAttribute(
      "href",
      "/models/4",
    );
  });

  it("preserves multiple filament values", async () => {
    const user = userEvent.setup();
    renderApp(<SlicerProfileDetails />, {
      seed: [[slicerProfileKeys.page(null), { items: [profile], next_before_id: null }]],
    });

    await user.click(await screen.findByRole("button", { name: "View settings" }));

    expect(screen.getByText("0.98;1.02")).toBeVisible();
  });

  it("shows process settings when selected", async () => {
    const user = userEvent.setup();
    renderApp(<SlicerProfileDetails />, {
      seed: [[slicerProfileKeys.page(null), { items: [profile], next_before_id: null }]],
    });

    await user.click(await screen.findByRole("button", { name: "View settings" }));
    await user.click(screen.getByRole("tab", { name: "Process settings" }));

    expect(screen.getByText("layer_height")).toBeVisible();
  });

  it("filters settings by value", async () => {
    const user = userEvent.setup();
    renderApp(<SlicerProfileDetails />, {
      seed: [[slicerProfileKeys.page(null), { items: [profile], next_before_id: null }]],
    });
    await user.click(await screen.findByRole("button", { name: "View settings" }));

    await user.type(screen.getByRole("textbox", { name: "Find a setting or value" }), "0.98");

    expect(screen.getAllByRole("term").map((term) => term.textContent)).toEqual([
      "filament_flow_ratio",
    ]);
  });

  it("shows no matching settings", async () => {
    const user = userEvent.setup();
    renderApp(<SlicerProfileDetails />, {
      seed: [[slicerProfileKeys.page(null), { items: [profile], next_before_id: null }]],
    });
    await user.click(await screen.findByRole("button", { name: "View settings" }));

    await user.type(screen.getByRole("textbox", { name: "Find a setting or value" }), "missing");

    expect(screen.getByText("No matching settings were captured in this group.")).toBeVisible();
  });

  it("shows an empty page without claiming a backup", async () => {
    renderApp(<SlicerProfileDetails />, {
      seed: [[slicerProfileKeys.page(null), { items: [], next_before_id: null }]],
    });

    expect(await screen.findByText("No captured settings on this page")).toBeVisible();
    expect(screen.getByText(/This is not a complete preset backup/)).toBeVisible();
  });

  it("advances to the next bounded page", async () => {
    const user = userEvent.setup();
    renderApp(<SlicerProfileDetails />, {
      seed: [[slicerProfileKeys.page(null), { items: [profile], next_before_id: 10 }]],
      routes: {
        "GET /api/v1/slicer-profiles": json({
          items: [{ ...profile, file_id: 9, filename: "older.gcode" }],
          next_before_id: null,
        }),
      },
    });

    await user.click(await screen.findByRole("button", { name: "Older files" }));

    expect(await screen.findByText("older.gcode")).toBeVisible();
    expect(screen.queryByText("bracket.gcode")).not.toBeInTheDocument();
  });

  it("offers retry after a failed read", async () => {
    renderApp(<SlicerProfileDetails />, {
      routes: { "GET /api/v1/slicer-profiles": json({ detail: "unavailable" }, 503) },
    });

    expect(
      within(await screen.findByRole("alert")).getByRole("button", { name: "Retry" }),
    ).toBeVisible();
  });

  it("refreshes newly captured settings", async () => {
    const user = userEvent.setup();
    renderApp(<SlicerProfileDetails />, {
      seed: [[slicerProfileKeys.page(null), { items: [], next_before_id: null }]],
      routes: { "GET /api/v1/slicer-profiles": json({ items: [profile], next_before_id: null }) },
    });

    await user.click(screen.getByRole("button", { name: "Refresh" }));

    expect(await screen.findByText("bracket.gcode")).toBeVisible();
  });

  it("hides cached settings after access is denied", async () => {
    const user = userEvent.setup();
    renderApp(<SlicerProfileDetails />, {
      seed: [[slicerProfileKeys.page(null), { items: [profile], next_before_id: null }]],
      routes: { "GET /api/v1/slicer-profiles": json({ detail: "access_denied" }, 403) },
    });

    await user.click(screen.getByRole("button", { name: "Refresh" }));
    await screen.findByRole("alert");

    expect(screen.queryByText("bracket.gcode")).not.toBeInTheDocument();
  });

  it("returns to the newer page", async () => {
    const user = userEvent.setup();
    renderApp(<SlicerProfileDetails />, {
      seed: [
        [slicerProfileKeys.page(null), { items: [profile], next_before_id: 10 }],
        [slicerProfileKeys.page(10), { items: [], next_before_id: null }],
      ],
    });
    await user.click(screen.getByRole("button", { name: "Older files" }));

    await user.click(await screen.findByRole("button", { name: "Newer files" }));

    expect(await screen.findByText("bracket.gcode")).toBeVisible();
  });

  it("collapses expanded settings", async () => {
    const user = userEvent.setup();
    renderApp(<SlicerProfileDetails />, {
      seed: [[slicerProfileKeys.page(null), { items: [profile], next_before_id: null }]],
    });
    await user.click(screen.getByRole("button", { name: "View settings" }));

    await user.click(screen.getByRole("button", { name: "Hide settings" }));

    expect(screen.queryByText("filament_flow_ratio")).not.toBeInTheDocument();
  });
});
