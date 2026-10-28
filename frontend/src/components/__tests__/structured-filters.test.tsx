/*
 * The facet panel: eight filter groups over whatever the library actually holds.
 *
 * Every option here comes from a facet count the server computed under the
 * *current* filters, which is what makes the numbers beside each option mean
 * anything. A group rendered from a hard-coded list instead would offer values
 * that match nothing and hide values that do — and the user has no way to tell
 * an empty result from a filter that was never available.
 *
 * Selection is multi-value and additive within a group: picking PLA and then
 * PETG means "either", not "PETG instead". Getting that wrong turns every second
 * click into a silent replacement of the first.
 *
 * The two failure states are deliberately different from each other. While the
 * counts are loading the groups still render, because collapsing them would make
 * the sidebar jump under the cursor; when the request failed the panel says so,
 * because silently showing zero options reads as "you have nothing", which is a
 * lie about the library rather than about the request.
 */

import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { StructuredFilters } from "@/components/structured-filters";
import type { ModelFacetsRead } from "@/types";

type Props = Parameters<typeof StructuredFilters>[0];

/**
 * The rendered label for the `file_type` group. It says "File type" like the
 * active-filter chip ("File type: STL") and the Spanish panel ("Tipo de archivo").
 */
const FILE_TYPE_GROUP = "File type";

const FACETS: ModelFacetsRead = {
  file_type: [
    { value: "stl", count: 12 },
    { value: "gcode", count: 4 },
  ],
  material_type: [{ value: "PLA", count: 9 }],
  slicer_name: [{ value: "OrcaSlicer", count: 3 }],
  printer_model: [],
  revision_status: [{ value: "known_good", count: 2 }],
  print_outcome: [],
  storage: [{ value: "vault", count: 12 }],
  printed: [],
};

function renderFilters(over: Partial<Props> = {}) {
  const onChange = vi.fn<Props["onChange"]>();
  const onDateChange = vi.fn<NonNullable<Props["onDateChange"]>>();
  const onClearAll = vi.fn<NonNullable<Props["onClearAll"]>>();
  const result = render(
    <StructuredFilters
      facets={FACETS}
      active={{}}
      onChange={onChange}
      onDateChange={onDateChange}
      onClearAll={onClearAll}
      {...over}
    />,
  );
  return { ...result, onChange, onDateChange, onClearAll };
}

describe("StructuredFilters", () => {
  describe("what it offers", () => {
    it("lists the values the library actually holds", async () => {
      renderFilters();
      await userEvent.setup().click(screen.getByRole("button", { name: FILE_TYPE_GROUP }));
      await userEvent.setup().click(screen.getByRole("button", { name: "Material" }));

      expect(screen.getByText("STL")).toBeInTheDocument();
      expect(screen.getByText("PLA")).toBeInTheDocument();
    });

    it("writes file formats the way they name themselves", async () => {
      renderFilters();
      await userEvent.setup().click(screen.getByRole("button", { name: FILE_TYPE_GROUP }));

      expect(screen.getByText("STL")).toBeInTheDocument();
      expect(screen.getByText("G-code")).toBeInTheDocument();
    });

    it("lists sliced G-code after the source formats", async () => {
      // G-code is the output of a source format, not another one of them; mixed
      // in by count it sat between STL and 3MF.
      renderFilters({
        facets: {
          ...FACETS,
          file_type: [
            { value: "gcode", count: 40 },
            { value: "stl", count: 12 },
            { value: "3mf", count: 3 },
          ],
        },
      });
      await userEvent.setup().click(screen.getByRole("button", { name: FILE_TYPE_GROUP }));

      const options = screen
        .getAllByRole("checkbox")
        .map((box) => box.closest("label")?.textContent);
      expect(options.filter((text) => /STL|3MF|G-code/.test(text ?? ""))).toEqual([
        "STL12",
        "3MF3",
        "G-code40",
      ]);
    });

    it("shows a material name as the library wrote it", async () => {
      renderFilters({ facets: { ...FACETS, material_type: [{ value: "pla", count: 9 }] } });
      await userEvent.setup().click(screen.getByRole("button", { name: "Material" }));

      expect(screen.getByText("pla")).toBeInTheDocument();
    });

    it("shows how many models each value matches", async () => {
      // The count is what makes a facet worth clicking; without it the user is
      // guessing which filter narrows anything.
      renderFilters();

      await userEvent.setup().click(screen.getByRole("button", { name: FILE_TYPE_GROUP }));
      expect(screen.getByText("12")).toBeInTheDocument();
    });

    it("leaves out a group the library has nothing for", () => {
      renderFilters();

      expect(screen.queryByText("Printer model")).toBeNull();
    });
  });

  describe("choosing values", () => {
    it("reports the value the user picked", async () => {
      const user = userEvent.setup();
      const { onChange } = renderFilters();

      await user.click(screen.getByRole("button", { name: FILE_TYPE_GROUP }));
      await user.click(screen.getByText("STL"));

      expect(onChange).toHaveBeenCalledWith("file_type", ["stl"]);
    });

    it("adds a second value to the first rather than replacing it", async () => {
      // Picking PLA and then PETG means "either". Replacing turns every second
      // click into a silent undo of the first.
      const user = userEvent.setup();
      const { onChange } = renderFilters({ active: { file_type: ["stl"] } });

      await user.click(screen.getByText("G-code"));

      expect(onChange).toHaveBeenCalledWith("file_type", ["stl", "gcode"]);
    });

    it("removes a value the user unpicks", async () => {
      const user = userEvent.setup();
      const { onChange } = renderFilters({ active: { file_type: ["stl", "gcode"] } });

      await user.click(screen.getByText("STL"));

      expect(onChange).toHaveBeenCalledWith("file_type", ["gcode"]);
    });
  });

  describe("collapsing a group", () => {
    it("hides a group's values when it is collapsed", async () => {
      const user = userEvent.setup();
      renderFilters({ active: { file_type: ["stl"] } });

      await user.click(screen.getByRole("button", { name: /File type/ }));

      expect(screen.queryByText("STL")).toBeNull();
    });

    it("brings them back when it is expanded again", async () => {
      const user = userEvent.setup();
      renderFilters();

      await user.click(screen.getByRole("button", { name: FILE_TYPE_GROUP }));

      expect(screen.getByText("STL")).toBeInTheDocument();
    });

    it("starts a rarely-used group collapsed", () => {
      // Eight groups expanded at once is a sidebar nobody can scan.
      renderFilters();

      expect(screen.queryByText("OrcaSlicer")).toBeNull();
    });
  });

  describe("one family of groups", () => {
    it("gives every group the same disclosure control", async () => {
      const user = userEvent.setup();
      renderFilters();

      for (const name of [FILE_TYPE_GROUP, "Print history", "Uploaded"]) {
        const toggle = screen.getByRole("button", { name });
        expect(toggle).toHaveAttribute("aria-controls");
        expect(toggle).toHaveAttribute("aria-expanded", "false");
        await user.click(toggle);
        expect(toggle).toHaveAttribute("aria-expanded", "true");
      }
    });

    it("keeps the print history fields in the panel's one-column dense layout", async () => {
      const user = userEvent.setup();
      renderFilters();

      await user.click(screen.getByRole("button", { name: "Print history" }));

      expect(screen.getByLabelText(/Finished on or after/)).toHaveClass("h-8", "text-xs");
    });

    it("opens a group that already holds a value", () => {
      renderFilters({ uploadedAfter: "2026-01-01" });

      const uploaded = screen.getByRole("button", { name: /Uploaded/ });
      expect(uploaded).toHaveAttribute("aria-expanded", "true");
      expect(uploaded).toHaveTextContent("1");
    });
  });

  describe("the upload date window", () => {
    it("reports the start of the window", async () => {
      const user = userEvent.setup();
      const { onDateChange } = renderFilters();

      await user.click(screen.getByRole("button", { name: "Uploaded" }));
      await user.type(screen.getByLabelText("After"), "2026-01-01");

      expect(onDateChange).toHaveBeenCalledWith("uploaded_after", "2026-01-01");
    });

    it("reports the end of the window", async () => {
      const user = userEvent.setup();
      const { onDateChange } = renderFilters();

      await user.click(screen.getByRole("button", { name: "Uploaded" }));
      await user.type(screen.getByLabelText("Before"), "2026-02-01");

      expect(onDateChange).toHaveBeenCalledWith("uploaded_before", "2026-02-01");
    });

    it("counts an active date window as a filter to clear", async () => {
      const user = userEvent.setup();
      const { onClearAll } = renderFilters({ uploadedAfter: "2026-01-01" });

      await user.click(screen.getByRole("button", { name: /Clear/ }));

      expect(onClearAll).toHaveBeenCalledTimes(1);
    });

    it("clears each group itself when the caller offers no handler", async () => {
      // The panel owns the reset when nothing above it does, so a consumer that
      // only wires `onChange` still gets a working Clear.
      const user = userEvent.setup();
      const { onChange } = renderFilters({
        active: { file_type: ["stl"] },
        onClearAll: undefined,
      });

      await user.click(screen.getByRole("button", { name: /Clear/ }));

      expect(onChange).toHaveBeenCalledWith("file_type", []);
    });
  });

  describe("clearing", () => {
    it("offers to clear everything once something is active", async () => {
      const user = userEvent.setup();
      const { onClearAll } = renderFilters({ active: { file_type: ["stl"] } });

      await user.click(screen.getByRole("button", { name: /Clear/ }));

      expect(onClearAll).toHaveBeenCalledTimes(1);
    });

    it("offers nothing to clear when no filter is active", () => {
      renderFilters();

      expect(screen.queryByRole("button", { name: /Clear/ })).toBeNull();
    });
  });

  describe("while the counts are unavailable", () => {
    it("says the values are still coming", async () => {
      renderFilters({ facets: undefined, loading: true });

      expect(
        await screen.findByRole("status", { name: "Loading filter values…" }),
      ).toBeInTheDocument();
    });

    it("keeps an already-active filter visible while they load", async () => {
      // The group is the only way back out of the filter, so it survives a
      // reload of the counts even though its options have not arrived.
      renderFilters({ facets: undefined, loading: true, active: { file_type: ["stl"] } });

      // The badge carrying the selected count joins the accessible name.
      expect(
        await screen.findByRole("button", { name: new RegExp(FILE_TYPE_GROUP) }),
      ).toBeInTheDocument();
    });

    it("says so when the counts could not be fetched", () => {
      // Silently showing zero options reads as "you have nothing", which is a
      // lie about the library rather than about the request.
      renderFilters({ facets: undefined, error: true });

      expect(screen.getByText("Filter values could not be loaded.")).toBeInTheDocument();
    });
  });
});

describe("StructuredFilters inline", () => {
  function StatefulFilters({
    facets = FACETS,
    active = {},
    uploadedAfter,
    uploadedBefore,
    history = {},
    ...props
  }: Partial<Props>) {
    const [selected, setSelected] = useState(active);
    const [dates, setDates] = useState({
      uploaded_after: uploadedAfter,
      uploaded_before: uploadedBefore,
      ...history,
    });
    return (
      <StructuredFilters
        layout="inline"
        facets={facets}
        active={selected}
        uploadedAfter={dates.uploaded_after}
        uploadedBefore={dates.uploaded_before}
        history={dates}
        onChange={(key, values) => setSelected((current) => ({ ...current, [key]: values }))}
        onDateChange={(key, value) => setDates((current) => ({ ...current, [key]: value }))}
        {...props}
      />
    );
  }

  it("keeps restored date filters closed until requested", () => {
    render(
      <StatefulFilters uploadedAfter="2026-01-01" history={{ printed_after: "2026-01-01" }} />,
    );
    expect(screen.getByRole("button", { name: "Uploaded" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.getByRole("button", { name: "Print history" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.queryByLabelText("After")).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("restores the upload range inside its dropdown", async () => {
    render(<StatefulFilters uploadedAfter="2026-01-01" uploadedBefore="2026-02-01" />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Uploaded" }));
    const panel = within(screen.getByRole("dialog", { name: "Uploaded" }));
    expect(panel.getByLabelText("After")).toHaveValue("2026-01-01");
    expect(panel.getByLabelText("Before")).toHaveValue("2026-02-01");
    expect(panel.getByLabelText("After")).toHaveAttribute("type", "date");
    expect(panel.getByLabelText("Before")).toHaveAttribute("type", "date");
  });

  it("offers calendar dates alongside print durations", async () => {
    render(
      <StatefulFilters
        history={{
          printed_after: "2026-01-01",
          printed_before: "2026-02-01",
          print_duration_min_s: 60,
        }}
      />,
    );
    await userEvent.setup().click(screen.getByRole("button", { name: "Print history" }));
    const panel = within(screen.getByRole("dialog", { name: "Print history" }));
    expect(panel.getByLabelText(/Finished on or after/)).toHaveAttribute("type", "date");
    expect(panel.getByLabelText(/Finished before/)).toHaveAttribute("type", "date");
    expect(panel.getByLabelText(/Finished on or after/)).toHaveValue("2026-01-01");
    expect(panel.getByLabelText(/Finished before/)).toHaveValue("2026-02-01");
    expect(panel.getByLabelText(/Actual duration ≥/)).toHaveValue(60);
  });

  it("preserves a saved timestamp until the user edits its date", async () => {
    const { onDateChange } = renderFilters({
      layout: "inline",
      history: { printed_after: "2026-01-01T12:30:00Z" },
    });
    await userEvent.setup().click(screen.getByRole("button", { name: "Print history" }));
    expect(screen.getByLabelText(/Finished on or after/)).toHaveValue("2026-01-01");
    expect(screen.getByLabelText(/Finished on or after/)).toHaveAttribute(
      "title",
      "2026-01-01T12:30:00Z",
    );
    expect(onDateChange).not.toHaveBeenCalled();
  });

  it.each([
    { label: "upload start", menu: "Uploaded", field: "After" },
    { label: "upload end", menu: "Uploaded", field: "Before" },
    { label: "print start", menu: "Print history", field: "Finished on or after" },
    { label: "print end", menu: "Print history", field: "Finished before" },
  ])("updates the $label date without closing its dropdown", async ({ menu, field }) => {
    render(<StatefulFilters />);
    await userEvent.setup().click(screen.getByRole("button", { name: menu }));
    fireEvent.change(screen.getByLabelText(field), { target: { value: "2026-02-01" } });
    expect(screen.getByLabelText(field)).toHaveValue("2026-02-01");
    expect(screen.getByRole("dialog", { name: menu })).toBeVisible();
  });

  it("clears a date without closing its dropdown", async () => {
    render(<StatefulFilters history={{ printed_after: "2026-01-01" }} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Print history" }));
    fireEvent.change(screen.getByLabelText("Finished on or after"), { target: { value: "" } });
    expect(screen.getByLabelText("Finished on or after")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Print history" })).toHaveTextContent(
      /^Print history$/,
    );
  });

  it("keeps multiple file types selected in the dropdown", async () => {
    const user = userEvent.setup();
    render(<StatefulFilters />);
    await user.click(screen.getByRole("button", { name: "File type" }));
    await user.click(screen.getByRole("checkbox", { name: "STL" }));
    await user.click(screen.getByRole("checkbox", { name: "G-code" }));
    expect(screen.getByRole("checkbox", { name: "STL" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "G-code" })).toBeChecked();
    expect(screen.getByRole("button", { name: "File type" })).toHaveTextContent("STL, G-code");
    expect(within(screen.getByRole("dialog", { name: "File type" })).getByText("12")).toBeVisible();
  });

  it("allows removing an active value before its facet count arrives", async () => {
    const user = userEvent.setup();
    render(
      <StatefulFilters
        facets={{ ...FACETS, file_type: [] }}
        active={{ file_type: ["3mf"] }}
        loading
      />,
    );
    await user.click(screen.getByRole("button", { name: "File type" }));
    expect(screen.getByRole("checkbox", { name: "3MF" })).toBeChecked();
    await user.click(screen.getByRole("checkbox", { name: "3MF" }));
    expect(screen.queryByRole("button", { name: "File type" })).not.toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Loading filter values…" })).toBeVisible();
  });

  it("retains available selections when pending counts become ready", async () => {
    const onChange = vi.fn<Props["onChange"]>();
    const view = renderFilters({
      layout: "inline",
      facets: undefined,
      loading: true,
      active: { file_type: ["3mf"] },
      onChange,
    });
    await userEvent.setup().click(screen.getByRole("button", { name: "File type" }));
    view.rerender(
      <StructuredFilters
        layout="inline"
        facets={{
          ...FACETS,
          file_type: [
            { value: "3mf", count: 7 },
            { value: "stl", count: 12 },
          ],
        }}
        active={{ file_type: ["3mf"] }}
        onChange={onChange}
      />,
    );
    expect(screen.queryByRole("status", { name: "Loading filter values…" })).toBeNull();
    expect(screen.getByRole("checkbox", { name: "3MF" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "STL" })).toBeEnabled();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("keeps loaded values interactive during a refresh", async () => {
    const user = userEvent.setup();
    render(<StatefulFilters loading />);
    await user.click(screen.getByRole("button", { name: "File type" }));
    await user.click(screen.getByRole("checkbox", { name: "STL" }));
    expect(screen.getByRole("checkbox", { name: "STL" })).toBeChecked();
    expect(screen.getByRole("button", { name: "Material" })).toBeEnabled();
  });

  it("replaces the printed status with an exclusive selection", async () => {
    const user = userEvent.setup();
    render(
      <StatefulFilters
        facets={{
          ...FACETS,
          printed: [
            { value: "yes", count: 0 },
            { value: "no", count: 4 },
          ],
        }}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Printed" }));
    expect(screen.getByRole("radio", { name: "All" })).toBeChecked();
    expect(within(screen.getByRole("dialog", { name: "Printed" })).getByText("0")).toBeVisible();
    await user.click(screen.getByRole("radio", { name: "Yes" }));
    await user.click(screen.getByRole("radio", { name: "No" }));
    expect(screen.getByRole("radio", { name: "Yes" })).not.toBeChecked();
    expect(screen.getByRole("radio", { name: "No" })).toBeChecked();
    expect(screen.getByRole("button", { name: "Printed" })).toHaveTextContent("No");
  });

  it("clears the printed status with All when its count is unavailable", async () => {
    const user = userEvent.setup();
    render(<StatefulFilters active={{ printed: ["no"] }} />);
    await user.click(screen.getByRole("button", { name: "Printed" }));
    expect(screen.getByRole("radio", { name: "No" })).toBeChecked();
    await user.click(screen.getByRole("radio", { name: "All" }));
    expect(screen.queryByRole("button", { name: "Printed" })).not.toBeInTheDocument();
  });

  it.each(["Uploaded", "Print history", "File type", "Material"])(
    "returns keyboard focus to %s on Escape",
    async (name) => {
      const user = userEvent.setup();
      render(<StatefulFilters />);
      const trigger = screen.getByRole("button", { name });
      await user.click(trigger);
      await user.tab();
      await user.keyboard("{Escape}");
      expect(trigger).toHaveFocus();
      expect(trigger).toHaveAttribute("aria-expanded", "false");
      await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    },
  );

  it("dismisses a date dropdown on an outside click", async () => {
    const user = userEvent.setup();
    render(<StatefulFilters />);
    await user.click(screen.getByRole("button", { name: "Uploaded" }));
    await user.click(screen.getByRole("checkbox", { name: "Has similar candidates" }));
    expect(screen.getByRole("button", { name: "Uploaded" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});
