/** Imports offers the published Chrome listing while retaining source access. */
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MakerWorldConnectCard } from "@/components/makerworld-connect-card";
import { renderApp } from "@/test-support/render";

describe("MakerWorldConnectCard", () => {
  it("links directly to the published Chrome extension", () => {
    renderApp(<MakerWorldConnectCard />);
    expect(screen.getByRole("link", { name: "Install Chrome extension" })).toHaveAttribute(
      "href",
      "https://chromewebstore.google.com/detail/printstash/dfeakldahcajangoijfldionahhbeajg",
    );
  });

  it("opens the install link without sharing the opener", () => {
    renderApp(<MakerWorldConnectCard />);
    const link = screen.getByRole("link", { name: "Install Chrome extension" });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("keeps extension source instructions available", () => {
    renderApp(<MakerWorldConnectCard />);
    expect(screen.getByRole("link", { name: "Open extension source" })).toHaveAttribute(
      "href",
      "https://github.com/xiao-villamor/PrintStash/tree/main/browser-extension",
    );
  });

  it("localizes the Chrome installation action", () => {
    renderApp(<MakerWorldConnectCard />, { locale: "es" });
    expect(screen.getByRole("link", { name: "Instalar extensión de Chrome" })).toHaveAttribute(
      "href",
      "https://chromewebstore.google.com/detail/printstash/dfeakldahcajangoijfldionahhbeajg",
    );
  });
});
