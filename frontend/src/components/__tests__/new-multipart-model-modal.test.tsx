/** Destination search shares ZIP's picker without losing the multipart draft. */
import "@testing-library/jest-dom/vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { NewMultipartModelModal } from "@/components/new-multipart-model-modal";
import { collectionTreeRoutes } from "@/test-support/collection-tree";
import { aCollection, aCollectionNode, aMultipartModel } from "@/test-support/factories";
import { json, renderApp } from "@/test-support/render";

const parent = aCollection({ id: 1, name: "Workshop", path: "workshop", parent_id: null });
const child = aCollection({
  id: 2,
  name: "Brackets",
  path: "workshop/brackets",
  parent_id: 1,
});

function renderModal(collection: ReturnType<typeof aCollectionNode> | null = null) {
  const onClose = vi.fn<() => void>();
  const view = renderApp(
    <NewMultipartModelModal open onClose={onClose} collection={collection} />,
    {
      routes: {
        ...collectionTreeRoutes([parent, child]),
        "POST /api/v1/multipart-models": json(aMultipartModel()),
      },
    },
  );
  return { ...view, onClose };
}

describe("NewMultipartModelModal destination", () => {
  it("loads destinations only after opening the picker", async () => {
    const user = userEvent.setup();
    const view = renderModal();

    await waitFor(() =>
      expect(screen.queryByRole("textbox", { name: "Find destination" })).toBeNull(),
    );
    expect(view.requests().filter(({ url }) => url.includes("/collections/search"))).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Collection" }));
    expect(await screen.findByRole("option", { name: /Workshop\/Brackets/ })).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Find destination" })).toHaveFocus();
  });

  it("creates the set in the searched destination", async () => {
    const user = userEvent.setup();
    const view = renderModal();
    await user.type(screen.getByLabelText("Name", { exact: true }), "  Desk organiser  ");
    await user.type(screen.getByLabelText("Description"), "  Printed parts  ");
    await user.click(screen.getByRole("button", { name: "Collection" }));
    await screen.findByRole("option", { name: /Workshop\/Brackets/ });
    const search = screen.getByRole("textbox", { name: "Find destination" });
    await waitFor(() => expect(search).toHaveFocus());
    await user.type(search, "brack");
    expect(search).toHaveValue("brack");
    await waitFor(() => expect(screen.queryByRole("option", { name: /^Workshop \(/ })).toBeNull());
    await user.click(await screen.findByRole("option", { name: /Workshop\/Brackets/ }));

    await waitFor(() =>
      expect(screen.queryByRole("textbox", { name: "Find destination" })).toBeNull(),
    );
    expect(screen.getByRole("button", { name: "Collection" })).toHaveTextContent("Brackets");
    expect(screen.getByText("Workshop/Brackets")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Create multipart set" }));
    await waitFor(() => expect(view.requestsWithMethod("POST")).toHaveLength(1));
    expect(JSON.parse(view.requestsWithMethod("POST")[0]!.body)).toEqual({
      name: "Desk organiser",
      description: "Printed parts",
      collection_id: 2,
    });
    await waitFor(() => expect(view.onClose).toHaveBeenCalledOnce());
  });

  it("dismisses only the picker on Escape", async () => {
    const user = userEvent.setup();
    const { onClose } = renderModal();
    await user.type(screen.getByLabelText("Name", { exact: true }), "Keep this draft");
    const trigger = screen.getByRole("button", { name: "Collection" });
    await user.click(trigger);
    await screen.findByRole("textbox", { name: "Find destination" });
    await user.keyboard("{Escape}");

    await waitFor(() =>
      expect(screen.queryByRole("textbox", { name: "Find destination" })).toBeNull(),
    );
    expect(screen.getByLabelText("Name", { exact: true })).toHaveValue("Keep this draft");
    expect(trigger).toHaveFocus();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("clears the initial folder through Vault only", async () => {
    const user = userEvent.setup();
    const view = renderModal(
      aCollectionNode({
        ...child,
        display_path: "Workshop/Brackets",
      }),
    );
    const trigger = screen.getByRole("button", { name: "Collection" });
    expect(trigger).toHaveTextContent("Brackets");
    await user.type(screen.getByLabelText("Name", { exact: true }), "Loose set");
    await user.click(trigger);
    const picker = screen.getByRole("dialog", { name: "Collection" });
    expect(
      await within(picker).findByRole("option", { name: /Workshop\/Brackets/ }),
    ).toHaveAttribute("aria-selected", "true");
    await user.click(within(picker).getByRole("option", { name: "Vault only" }));
    await user.click(screen.getByRole("button", { name: "Create multipart set" }));
    await waitFor(() => expect(view.requestsWithMethod("POST")).toHaveLength(1));
    expect(JSON.parse(view.requestsWithMethod("POST")[0]!.body)).toEqual({
      name: "Loose set",
      description: null,
      collection_id: null,
    });
  });
});
