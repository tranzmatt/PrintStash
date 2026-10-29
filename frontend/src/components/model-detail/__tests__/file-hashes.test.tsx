/** File digests stay complete, paired with their Artifact, and independent of optional geometry enrichment. */
import "@testing-library/jest-dom/vitest";
import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { FileHashes } from "../file-hashes";
import { aRevision } from "@/test-support/factories";
import { renderApp } from "@/test-support/render";

const FILE_SHA = "0123456789abcdef".repeat(4);
const GEOMETRIC_SHA = "fedcba9876543210".repeat(4);

describe("FileHashes", () => {
  afterEach(() => vi.restoreAllMocks());
  it("shows a short file SHA with its full value on hover", () => {
    renderApp(<FileHashes files={[aRevision({ sha256: FILE_SHA })]} />);
    const hashes = screen.getByRole("region", { name: "File hashes" });
    expect(within(hashes).getByText(FILE_SHA.slice(0, 7), { exact: true })).toBeVisible();
    expect(within(hashes).getByTitle(FILE_SHA, { exact: true })).toBeVisible();
    expect(within(hashes).queryByText(FILE_SHA, { exact: true })).not.toBeInTheDocument();
    expect(within(hashes).queryByText("Geometric SHA-256")).not.toBeInTheDocument();
  });

  it("pairs each calculated geometry SHA with its own filename", () => {
    renderApp(
      <FileHashes
        files={[
          aRevision({
            id: 1,
            original_filename: "cube.stl",
            sha256: FILE_SHA,
            geometric_sha256: GEOMETRIC_SHA,
          }),
          aRevision({ id: 2, original_filename: "cube.gcode", sha256: "b".repeat(64) }),
        ]}
      />,
    );
    const file = screen.getByText("cube.stl").parentElement!;
    expect(within(file).getByTitle(GEOMETRIC_SHA, { exact: true })).toHaveTextContent(
      GEOMETRIC_SHA.slice(0, 7),
    );
    expect(
      within(screen.getByText("cube.gcode").parentElement!).queryByText("Geometric SHA-256"),
    ).not.toBeInTheDocument();
  });

  it("omits the section for a Model without live files", () => {
    renderApp(<FileHashes files={[]} />);
    expect(screen.queryByRole("region", { name: "File hashes" })).not.toBeInTheDocument();
  });

  it.each([
    { kind: "File SHA-256", digest: FILE_SHA },
    { kind: "Geometric SHA-256", digest: GEOMETRIC_SHA },
  ])("copies the full $kind", async ({ kind, digest }) => {
    const user = userEvent.setup();
    renderApp(
      <FileHashes
        files={[
          aRevision({
            original_filename: "cube.stl",
            sha256: FILE_SHA,
            geometric_sha256: GEOMETRIC_SHA,
          }),
        ]}
      />,
    );
    await user.click(screen.getByRole("button", { name: `Copy ${kind} for cube.stl` }));
    expect(await navigator.clipboard.readText()).toBe(digest);
    expect(await screen.findByText("SHA-256 copied")).toBeInTheDocument();
  });

  it("reports a clipboard failure without confirming a copy", async () => {
    const user = userEvent.setup();
    vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(new Error("Clipboard denied"));
    renderApp(<FileHashes files={[aRevision({ sha256: FILE_SHA })]} />);
    await user.click(screen.getByTitle(FILE_SHA));
    expect(await screen.findByText("Could not copy SHA-256.")).toBeVisible();
    expect(screen.queryByText("SHA-256 copied")).not.toBeInTheDocument();
  });

  it("clears copy feedback when focus leaves", async () => {
    const user = userEvent.setup();
    renderApp(<FileHashes files={[aRevision({ sha256: FILE_SHA })]} />);
    await user.click(screen.getByTitle(FILE_SHA));
    expect(await screen.findByText("SHA-256 copied")).toBeInTheDocument();
    await user.tab();
    expect(screen.queryByText("SHA-256 copied")).not.toBeInTheDocument();
  });
});
