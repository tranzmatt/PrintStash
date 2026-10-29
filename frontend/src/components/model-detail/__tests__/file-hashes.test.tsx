/** File digests stay complete, paired with their Artifact, and independent of optional geometry enrichment. */
import "@testing-library/jest-dom/vitest";
import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FileHashes } from "../file-hashes";
import { aRevision } from "@/test-support/factories";
import { renderApp } from "@/test-support/render";

const FILE_SHA = "0123456789abcdef".repeat(4);
const GEOMETRIC_SHA = "fedcba9876543210".repeat(4);

describe("FileHashes", () => {
  it("shows the complete file SHA before geometry is calculated", () => {
    renderApp(<FileHashes files={[aRevision({ sha256: FILE_SHA })]} />);
    const hashes = screen.getByRole("region", { name: "File hashes" });
    expect(within(hashes).getByText(FILE_SHA, { exact: true })).toBeVisible();
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
    expect(within(file).getByText(GEOMETRIC_SHA, { exact: true })).toBeVisible();
    expect(
      within(screen.getByText("cube.gcode").parentElement!).queryByText("Geometric SHA-256"),
    ).not.toBeInTheDocument();
  });

  it("omits the section for a Model without live files", () => {
    renderApp(<FileHashes files={[]} />);
    expect(screen.queryByRole("region", { name: "File hashes" })).not.toBeInTheDocument();
  });
});
