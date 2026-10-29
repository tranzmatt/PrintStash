/** Search keeps precise timestamps while Library dropdowns expose calendar date inputs. */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PrintHistoryFields } from "@/components/print-history-fields";

describe("PrintHistoryFields", () => {
  it("retains precise timestamps in search", () => {
    render(
      <PrintHistoryFields
        value={{ printed_after: "2026-01-01T12:30:00Z" }}
        onChange={vi.fn<Parameters<typeof PrintHistoryFields>[0]["onChange"]>()}
      />,
    );
    expect(screen.getByLabelText("Finished on or after")).toHaveAttribute("type", "text");
    expect(screen.getByLabelText("Finished on or after")).toHaveValue("2026-01-01T12:30:00Z");
  });

  it("keeps numeric duration bounds in the calendar layout", () => {
    render(
      <PrintHistoryFields
        compact
        datePicker
        value={{ print_duration_min_s: 0, print_duration_max_s: 120 }}
        onChange={vi.fn<Parameters<typeof PrintHistoryFields>[0]["onChange"]>()}
      />,
    );
    expect(screen.getByLabelText(/Actual duration ≥/)).toHaveValue(0);
    expect(screen.getByLabelText(/Actual duration ≥/)).toHaveAttribute("min", "0");
    expect(screen.getByLabelText(/Actual duration </)).toHaveValue(120);
    expect(screen.getByLabelText(/Actual duration </)).toHaveAttribute("min", "1");
    expect(screen.getByLabelText(/Actual duration </)).toHaveAttribute("max", "2147483647");
  });
});
