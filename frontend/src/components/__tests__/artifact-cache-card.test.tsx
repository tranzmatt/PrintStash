/** Cache controls preserve active readers and separate policy changes from clearing. */
import "@testing-library/jest-dom/vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ArtifactCacheCard } from "@/components/artifact-cache-card";
import { renderApp } from "@/test-support/render";
import { anArtifactCache } from "@/test-support/factories";

const INITIAL = anArtifactCache();

describe("ArtifactCacheCard", () => {
  it("saves enabled policy without clearing files", async () => {
    let persisted = INITIAL;
    renderApp(
      <ArtifactCacheCard
        api={{
          read: async () => INITIAL,
          save: async (policy) => {
            persisted = { ...INITIAL, policy };
            return persisted;
          },
          reset: async () => INITIAL,
          clear: async () => {
            throw new Error("unexpected clear");
          },
        }}
      />,
    );
    await userEvent.click(
      await screen.findByRole("checkbox", { name: "Enable remote Artifact cache" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Save cache settings" }));
    expect(persisted.policy.enabled).toBe(true);
    expect(await screen.findByText(/100 bytes cached/)).toBeInTheDocument();
  });

  it("shows remaining leased bytes after clear", async () => {
    renderApp(
      <ArtifactCacheCard
        api={{
          read: async () => INITIAL,
          save: async () => INITIAL,
          reset: async () => INITIAL,
          clear: async () => ({ ...INITIAL, usage: { bytes: 25, entries: 1, leases: 1 } }),
        }}
      />,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Clear cached files" }));
    expect(await screen.findByText(/25 bytes cached/)).toHaveTextContent("1 active reads");
  });

  it("shows restart requirement after changing root", async () => {
    renderApp(
      <ArtifactCacheCard
        api={{
          read: async () => ({ ...INITIAL, restart_required: true }),
          save: async () => INITIAL,
          reset: async () => INITIAL,
          clear: async () => INITIAL,
        }}
      />,
    );
    expect(
      await screen.findByText("Restart PrintStash to use the new cache folder."),
    ).toBeInTheDocument();
  });

  it("allows retry after loading fails", async () => {
    let failed = true;
    renderApp(
      <ArtifactCacheCard
        api={{
          read: async () => {
            if (failed) throw new Error("unavailable");
            return INITIAL;
          },
          save: async () => INITIAL,
          reset: async () => INITIAL,
          clear: async () => INITIAL,
        }}
      />,
    );
    const retry = await screen.findByRole("button", { name: "Retry" });
    failed = false;
    await userEvent.click(retry);
    expect(
      await screen.findByRole("checkbox", { name: "Enable remote Artifact cache" }),
    ).toBeInTheDocument();
  });
});
