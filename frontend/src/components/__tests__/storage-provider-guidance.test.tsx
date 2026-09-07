import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StorageProviderGuidance } from "@/components/storage-provider-guidance";
import { storageProviderCatalogue } from "@/test-support/storage-provider-catalogue";
import { renderApp } from "@/test-support/render";
const garage = storageProviderCatalogue.find((provider) => provider.id === "garage")!;
describe("StorageProviderGuidance", () => {
  it.each([
    { locale: "en", instructions: "Provider setup instructions", text: "Transport tested." },
    { locale: "es", instructions: "Instrucciones del proveedor", text: "Transporte probado." },
  ] as const)("localizes preset guidance in $locale", ({ locale, instructions, text }) => {
    renderApp(<StorageProviderGuidance provider={garage} />, { locale });
    expect(screen.getByText(new RegExp(text))).toBeVisible();
    expect(screen.getByRole("link", { name: instructions })).toHaveAttribute(
      "href",
      garage.provider_documentation_url,
    );
    expect(screen.getByText(/3900/)).toBeVisible();
  });
  it("keeps delivery proof separate from deletion permission", () => {
    renderApp(<StorageProviderGuidance provider={garage} />);
    expect(screen.getByText(/Download support does not grant deletion permission/)).toBeVisible();
  });
  it("omits guidance for an older catalogue", () => {
    renderApp(<StorageProviderGuidance provider={{ ...garage, setup_guidance: undefined }} />);
    expect(screen.queryByRole("link")).toBeNull();
  });
});
