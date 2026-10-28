/** Destination search shares ZIP's picker without losing the multipart draft. */
import "@testing-library/jest-dom/vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { NewMultipartModelModal } from "@/components/new-multipart-model-modal";
import { collectionTreeRoutes } from "@/test-support/collection-tree";
import {
  aCollection,
  aCollectionNode,
  aMultipartModel,
  aModelListItem,
} from "@/test-support/factories";
import { json, renderApp, type RouteTable } from "@/test-support/render";

const parent = aCollection({ id: 1, name: "Workshop", path: "workshop", parent_id: null });
const child = aCollection({
  id: 2,
  name: "Brackets",
  path: "workshop/brackets",
  parent_id: 1,
});

function renderModal(
  collection: ReturnType<typeof aCollectionNode> | null = null,
  routes: RouteTable = {},
) {
  const onClose = vi.fn<() => void>();
  const view = renderApp(
    <NewMultipartModelModal open onClose={onClose} collection={collection} />,
    {
      routes: {
        ...collectionTreeRoutes([parent, child]),
        "POST /api/v1/multipart-models": json(aMultipartModel()),
        "GET /api/v1/models/page": json({ items: [], total: 0, next_cursor: null }),
        ...routes,
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

  it("creates selected models from different folders", async () => {
    const user = userEvent.setup();
    const rootModel = aModelListItem({
      id: 10,
      name: "Base",
      collection: null,
      collection_id: null,
    });
    const nestedModel = aModelListItem({
      id: 11,
      name: "Base",
      collection: "workshop/brackets",
      collection_id: 2,
      collection_label: "Workshop/Brackets",
    });
    const lid = aModelListItem({
      id: 12,
      name: "Lid",
      collection: "workshop/brackets",
      collection_id: 2,
    });
    const models = [rootModel, nestedModel, lid];
    const view = renderModal(null, {
      "GET /api/v1/models/page": (url) => {
        const params = new URL(url, "http://test").searchParams;
        const query = params.get("q");
        const items = models.filter((model) =>
          query ? model.name.includes(query) : model.collection === params.get("collection"),
        );
        return json({ items, total: items.length, next_cursor: null });
      },
    });
    await user.type(screen.getByLabelText("Name", { exact: true }), "Complete organiser");
    await user.click(await screen.findByRole("button", { name: "Base" }));
    await user.click(screen.getByRole("button", { name: "Open folder Workshop" }));
    await user.click(await screen.findByRole("button", { name: "Open folder Brackets" }));
    await screen.findByRole("button", { name: "Lid" });
    await user.click(screen.getByRole("button", { name: "Select this page" }));
    expect(screen.getByRole("status")).toHaveTextContent("3 selected");

    const search = screen.getByRole("textbox", { name: "Search existing models" });
    await user.type(search, "Base");
    await waitFor(() => expect(screen.queryByRole("button", { name: "Lid" })).toBeNull());
    expect(await screen.findAllByRole("button", { name: "Base" })).toHaveLength(2);
    for (const option of screen.getAllByRole("button", { name: "Base" })) {
      expect(option).toHaveAttribute("aria-pressed", "true");
    }
    await user.keyboard("{Enter}");
    expect(view.requestsWithMethod("POST")).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "Create multipart set" }));
    await waitFor(() => expect(view.requestsWithMethod("POST")).toHaveLength(1));
    expect(JSON.parse(view.requestsWithMethod("POST")[0]!.body)).toMatchObject({
      name: "Complete organiser",
      parts: [
        { name: "Base", quantity: 1, choices: [{ model_id: 10 }] },
        { name: "Base (2)", quantity: 1, choices: [{ model_id: 11 }] },
        { name: "Lid", quantity: 1, choices: [{ model_id: 12 }] },
      ],
    });
  });

  it("keeps selections across model pages", async () => {
    const user = userEvent.setup();
    renderModal(null, {
      "GET /api/v1/models/page": (url) => {
        const next = new URL(url, "http://test").searchParams.has("cursor");
        return json({
          items: [aModelListItem({ id: next ? 12 : 11, name: next ? "Lid" : "Base" })],
          total: 2,
          next_cursor: next ? null : "page-two",
        });
      },
    });
    await user.click(await screen.findByRole("button", { name: "Base" }));
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(await screen.findByRole("button", { name: "Lid" }));
    await user.click(screen.getByRole("button", { name: "Previous" }));
    expect(await screen.findByRole("button", { name: "Base" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("status")).toHaveTextContent("2 selected");
    await user.click(screen.getByRole("button", { name: "Clear selection" }));
    expect(screen.getByRole("status")).toHaveTextContent("0 selected");
    expect(screen.getByRole("button", { name: "Base" })).toHaveAttribute("aria-pressed", "false");
  });

  it("preserves the draft after a creation refusal", async () => {
    const user = userEvent.setup();
    const view = renderModal(null, {
      "GET /api/v1/models/page": json({
        items: [aModelListItem({ id: 11, name: "Base" })],
        total: 1,
        next_cursor: null,
      }),
      "POST /api/v1/multipart-models": json({ detail: "collection_permission_denied" }, 403),
    });
    await user.type(screen.getByLabelText("Name", { exact: true }), "My draft");
    await user.click(await screen.findByRole("button", { name: "Base" }));
    await user.click(screen.getByRole("button", { name: "Create multipart set" }));
    await screen.findByRole("alert");
    expect(screen.getByLabelText("Name", { exact: true })).toHaveValue("My draft");
    expect(screen.getByRole("button", { name: "Base" })).toHaveAttribute("aria-pressed", "true");
    expect(view.onClose).not.toHaveBeenCalled();
  });

  it("retries a failed model search", async () => {
    const user = userEvent.setup();
    const view = renderModal(null, {
      "GET /api/v1/models/page": json({ detail: "offline" }, 500),
    });
    await screen.findByRole("alert");
    view.route({
      "GET /api/v1/models/page": json({
        items: [aModelListItem({ id: 11, name: "Recovered model" })],
        total: 1,
        next_cursor: null,
      }),
    });
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("button", { name: "Recovered model" })).toBeVisible();
  });

  it("enforces the initial model limit across pages", async () => {
    const user = userEvent.setup();
    renderModal(null, {
      "GET /api/v1/models/page": (url) => {
        const offset = Number(new URL(url, "http://test").searchParams.get("cursor") ?? 0);
        const items = Array.from({ length: Math.min(24, 101 - offset) }, (_, index) =>
          aModelListItem({ id: offset + index + 1, name: "Piece " + (offset + index + 1) }),
        );
        return json({
          items,
          total: 101,
          next_cursor: offset + 24 < 101 ? String(offset + 24) : null,
        });
      },
    });
    for (let page = 0; page < 4; page++) {
      await screen.findByRole("button", { name: "Piece " + (page * 24 + 1) });
      await waitFor(() =>
        expect(screen.getByRole("button", { name: "Select this page" })).toBeEnabled(),
      );
      await user.click(screen.getByRole("button", { name: "Select this page" }));
      await user.click(screen.getByRole("button", { name: "Next" }));
    }
    await screen.findByRole("button", { name: "Piece 101" });
    expect(screen.getByRole("button", { name: "Select this page" })).toBeDisabled();
    for (const id of [97, 98, 99, 100])
      await user.click(screen.getByRole("button", { name: "Piece " + id }));
    expect(screen.getByRole("status")).toHaveTextContent("100 selected");
    expect(screen.getByRole("button", { name: "Piece 101" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Piece 100" }));
    expect(screen.getByRole("button", { name: "Piece 101" })).toBeEnabled();
  });
});
