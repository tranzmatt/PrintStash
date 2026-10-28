/** Equal observations group by preset and machine context, preserving distinct variants. */
import { describe, expect, it } from "vitest";
import { groupProfileSettings } from "@/lib/profile-settings";
import { aSlicerCapture } from "@/test-support/factories";

describe("groupProfileSettings", () => {
  it("groups equal settings regardless of key order", () => {
    const first = aSlicerCapture();
    const second = aSlicerCapture({
      file_id: 11,
      settings: {
        ...first.settings,
        filament: Object.fromEntries(Object.entries(first.settings.filament).reverse()),
      },
    });
    expect(
      groupProfileSettings("filament", [first, second]).map((v) => v.sources.map((s) => s.file_id)),
    ).toEqual([[10, 11]]);
  });
  it("preserves changed settings as variants", () => {
    const first = aSlicerCapture();
    const second = aSlicerCapture({
      file_id: 11,
      settings: {
        ...first.settings,
        filament: { ...first.settings.filament, filament_flow_ratio: "1" },
      },
    });
    expect(
      groupProfileSettings("filament", [first, second]).map((v) => v.settings.filament_flow_ratio),
    ).toEqual(["0.98;1.02", "1"]);
  });
  it.each([
    { label: "slicer", patch: { slicer_name: "BambuStudio" } },
    { label: "slicer version", patch: { slicer_version: "2.4" } },
    { label: "machine", patch: { printer_model: "Machine B" } },
    { label: "unknown slicer", patch: { slicer_name: null } },
    { label: "unknown machine", patch: { printer_model: null } },
  ])("keeps $label provenance separate", ({ patch }) => {
    const first = aSlicerCapture(
      patch.slicer_name === null || patch.printer_model === null ? patch : {},
    );
    expect(
      groupProfileSettings("filament", [first, aSlicerCapture({ ...patch, file_id: 11 })]),
    ).toHaveLength(2);
  });
  it("keeps printer configurations separate for a filament", () => {
    const first = aSlicerCapture();
    const second = aSlicerCapture({
      file_id: 11,
      settings: { ...first.settings, printer: { nozzle_diameter: "0.6" } },
    });
    expect(groupProfileSettings("filament", [first, second])).toHaveLength(2);
  });
  it("keeps process values on each source", () => {
    const first = aSlicerCapture();
    const second = aSlicerCapture({
      file_id: 11,
      settings: { ...first.settings, process: { layer_height: "0.3" } },
    });
    expect(
      groupProfileSettings("printer", [first, second])[0].sources.map(
        (s) => s.settings.process.layer_height,
      ),
    ).toEqual(["0.2", "0.3"]);
  });
  it("does not split printer variants by filament", () => {
    const first = aSlicerCapture();
    const second = aSlicerCapture({
      file_id: 11,
      settings: { ...first.settings, filament: { filament_type: "PETG" } },
    });
    expect(groupProfileSettings("printer", [first, second])).toHaveLength(1);
  });
  it("deduplicates a repeated source across pages", () => {
    const source = aSlicerCapture();
    expect(groupProfileSettings("printer", [source, source])[0].sources).toHaveLength(1);
  });
  it("omits empty settings groups", () => {
    const source = aSlicerCapture();
    expect(
      groupProfileSettings("filament", [
        { ...source, settings: { ...source.settings, filament: {} } },
      ]),
    ).toEqual([]);
  });
});
