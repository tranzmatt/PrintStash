/** General mobile navigation keeps manufacturing inside the Multipart workflow. */
import "@testing-library/jest-dom/vitest";
import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MobileNavDrawer } from "@/components/mobile-nav-drawer";
import { adminSession, memberSession, renderApp } from "@/test-support/render";

describe("MobileNavDrawer", () => {
  it.each([adminSession, memberSession])(
    "keeps Builds out of the navigation drawer (%#)",
    async (session) => {
      renderApp(<MobileNavDrawer open onClose={vi.fn<() => void>()} />, { auth: session() });
      expect(await screen.findByRole("dialog", { name: "Navigation" })).toBeVisible();
      expect(screen.queryByRole("link", { name: /Builds/i })).not.toBeInTheDocument();
      expect(screen.getByRole("link", { name: /Profiles/i })).toHaveAttribute("href", "/profiles");
    },
  );
});
