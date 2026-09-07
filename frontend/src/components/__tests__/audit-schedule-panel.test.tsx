import "@testing-library/jest-dom/vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AuditSchedulePanel } from "@/components/audit-schedule-panel";
import { anAuditPolicy } from "@/test-support/factories";
import { json, renderApp } from "@/test-support/render";

describe("Audit schedules", () => {
  it("saves an enabled schedule", async () => {
    const user = userEvent.setup();
    const view = renderApp(<AuditSchedulePanel />, {
      routes: {
        "GET /api/v1/maintenance/audit-policies": json([anAuditPolicy()]),
        "GET /api/v1/maintenance/audits": json([]),
        "PUT /api/v1/maintenance/audit-policies/quick": json(
          anAuditPolicy({ enabled: true, next_due_at: "2026-09-13T02:00:00Z", revision: 2 }),
        ),
      },
    });
    const form = await screen.findByRole("form", { name: "Quick audit schedule" });
    await user.click(within(form).getByRole("checkbox", { name: "Enabled" }));
    await user.click(within(form).getByRole("button", { name: "Save schedule" }));
    await waitFor(() =>
      expect(view.requestsWithMethod("PUT")[0]?.body).toContain('"enabled":true'),
    );
    expect(view.requestsWithMethod("PUT")[0]?.body).not.toContain('"revision"');
    expect(view.requestsWithMethod("PUT")[0]?.body).toContain('"expected_revision":1');
  });

  it("saves frequency, lateness and notification threshold controls", async () => {
    const user = userEvent.setup();
    const view = renderApp(<AuditSchedulePanel />, {
      routes: {
        "GET /api/v1/maintenance/audit-policies": json([anAuditPolicy()]),
        "GET /api/v1/maintenance/audits": json([]),
        "PUT /api/v1/maintenance/audit-policies/quick": json(anAuditPolicy({ revision: 2 })),
      },
    });
    const form = await screen.findByRole("form", { name: "Quick audit schedule" });
    await user.selectOptions(within(form).getByLabelText("Frequency"), "monthly");
    await user.selectOptions(
      within(form).getByLabelText("Issue notification threshold"),
      "critical",
    );
    await user.clear(within(form).getByLabelText("Overdue after (minutes)"));
    await user.type(within(form).getByLabelText("Overdue after (minutes)"), "45");
    await user.click(within(form).getByRole("button", { name: "Save schedule" }));
    await waitFor(() =>
      expect(view.requestsWithMethod("PUT")[0]?.body).toContain(
        '"notification_threshold":"critical"',
      ),
    );
    expect(view.requestsWithMethod("PUT")[0]?.body).toContain('"cadence":"monthly"');
    expect(view.requestsWithMethod("PUT")[0]?.body).toContain('"max_lateness_minutes":45');
  });

  it("saves a paused schedule", async () => {
    const user = userEvent.setup();
    const view = renderApp(<AuditSchedulePanel />, {
      routes: {
        "GET /api/v1/maintenance/audit-policies": json([anAuditPolicy({ enabled: true })]),
        "GET /api/v1/maintenance/audits": json([]),
        "PUT /api/v1/maintenance/audit-policies/quick": json(
          anAuditPolicy({ enabled: true, paused: true }),
        ),
      },
    });
    const form = await screen.findByRole("form", { name: "Quick audit schedule" });
    await user.click(within(form).getByRole("checkbox", { name: "Paused" }));
    await user.click(within(form).getByRole("button", { name: "Save schedule" }));
    await waitFor(() => expect(view.requestsWithMethod("PUT")[0]?.body).toContain('"paused":true'));
  });

  it("shows a recoverable loading failure", async () => {
    renderApp(<AuditSchedulePanel />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load audit schedules.");
    expect(screen.getByRole("button", { name: "Retry" })).toBeEnabled();
  });

  it("keeps an unsuccessful save editable", async () => {
    const user = userEvent.setup();
    renderApp(<AuditSchedulePanel />, {
      routes: {
        "GET /api/v1/maintenance/audit-policies": json([anAuditPolicy()]),
        "GET /api/v1/maintenance/audits": json([]),
        "PUT /api/v1/maintenance/audit-policies/quick": json({ detail: "invalid" }, 400),
      },
    });
    await user.click(await screen.findByRole("button", { name: "Save schedule" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not save audit schedule");
    expect(screen.getByRole("button", { name: "Save schedule" })).toBeEnabled();
  });
});
