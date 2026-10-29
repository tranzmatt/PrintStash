/**
 * A multi-plate 3MF offers each of its plates, and the whole build.
 *
 * The slicer labels plates 01, 02, …; the picker uses the same numbers and the
 * names the user gave them, so the plate chosen here is the plate they see in
 * the slicer. An empty plate has nothing to show and cannot be chosen.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { aFilePlate } from "@/test-support/factories";
import { renderApp } from "@/test-support/render";
import { PlatePicker } from "../plate-picker";

const PLATES = [
  aFilePlate(),
  aFilePlate({
    number: 2,
    name: "Wall mount",
    region: { min_x: 307.2, min_y: 0, max_x: 563.2, max_y: 256 },
  }),
];

describe("PlatePicker", () => {
  it("labels each plate as the slicer numbers it", () => {
    renderApp(<PlatePicker plates={PLATES} selected={null} onSelect={() => {}} />);

    expect(screen.getByRole("button", { name: /Plate 02.*Wall mount/ })).toBeVisible();
  });

  it("marks the whole build as shown when no plate is chosen", () => {
    renderApp(<PlatePicker plates={PLATES} selected={null} onSelect={() => {}} />);

    expect(screen.getByRole("button", { name: "All plates" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("marks the chosen plate as shown", () => {
    renderApp(<PlatePicker plates={PLATES} selected={2} onSelect={() => {}} />);

    expect(screen.getByRole("button", { name: /Plate 02/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("chooses a plate by its number", async () => {
    const onSelect = vi.fn<(plate: number | null) => void>();
    renderApp(<PlatePicker plates={PLATES} selected={null} onSelect={onSelect} />);

    await userEvent.click(screen.getByRole("button", { name: /Plate 02/ }));

    expect(onSelect).toHaveBeenCalledWith(2);
  });

  it("returns to the whole build", async () => {
    const onSelect = vi.fn<(plate: number | null) => void>();
    renderApp(<PlatePicker plates={PLATES} selected={2} onSelect={onSelect} />);

    await userEvent.click(screen.getByRole("button", { name: "All plates" }));

    expect(onSelect).toHaveBeenCalledWith(null);
  });

  it("labels an unnamed plate by its number alone", () => {
    renderApp(
      <PlatePicker
        plates={[aFilePlate({ name: null }), PLATES[1]!]}
        selected={null}
        onSelect={() => {}}
      />,
    );

    expect(screen.getByRole("button", { name: /^Plate 01\s*Objects: 1$/ })).toBeVisible();
  });

  it("refuses to choose a plate with nothing on it", () => {
    renderApp(
      <PlatePicker
        plates={[PLATES[0]!, aFilePlate({ number: 2, name: "Spare", object_count: 0 })]}
        selected={null}
        onSelect={() => {}}
      />,
    );

    expect(screen.getByRole("button", { name: /Plate 02/ })).toBeDisabled();
  });
});
