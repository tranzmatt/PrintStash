/**
 * A model page reads its 3MF's plates once, and again when they are derived.
 *
 * The plates of a fresh upload are not known until the `plates` derivative
 * settles; the page must then learn them without a reload. A model without a
 * 3MF has no plates to read and must not ask the server for any.
 */
import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setEventSocketFactory, type EventSocket } from "@/lib/events";
import { useFilePlates } from "@/lib/queries/file-plates";
import { aFilePlate } from "@/test-support/factories";
import { json, renderApp } from "@/test-support/render";
import type { FilePlates } from "@/types";

class FakeSocket implements EventSocket {
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  send = vi.fn<(data: string) => void>();
  close = vi.fn<() => void>();
}

const READY: FilePlates = {
  state: "ready",
  plates: [aFilePlate(), aFilePlate({ number: 2, name: "Wall mount" })],
};

function Probe({ fileId }: { fileId: number | null }) {
  const plates = useFilePlates(3, fileId);
  return (
    <p>
      {plates === null
        ? "unknown"
        : `${plates.state}: ${plates.plates.map((plate) => plate.name).join(", ")}`}
    </p>
  );
}

let socket: FakeSocket;

beforeEach(() => {
  socket = new FakeSocket();
  setEventSocketFactory(async () => socket);
});

describe("useFilePlates", () => {
  it("reads a 3MF's plates", async () => {
    renderApp(<Probe fileId={7} />, { routes: { "GET /api/v1/files/7/plates": json(READY) } });

    expect(await screen.findByText("ready: Main parts, Wall mount")).toBeVisible();
  });

  it("reads nothing for a model without a 3MF", () => {
    const view = renderApp(<Probe fileId={null} />);

    expect(screen.getByText("unknown")).toBeVisible();
    expect(view.requests()).toEqual([]);
  });

  it("reads again when the plates are derived", async () => {
    const view = renderApp(<Probe fileId={7} />, {
      routes: { "GET /api/v1/files/7/plates": json({ state: "pending", plates: [] }) },
    });
    await screen.findByText("pending:");
    await waitFor(() => expect(socket.onmessage).not.toBeNull());
    view.route({ "GET /api/v1/files/7/plates": json(READY) });

    socket.onmessage?.({
      data: JSON.stringify({
        type: "derivative",
        model_id: 3,
        file_id: 7,
        kind: "plates",
        state: "ready",
      }),
    });

    expect(await screen.findByText("ready: Main parts, Wall mount")).toBeVisible();
  });

  it("ignores a notice about another derivative", async () => {
    const view = renderApp(<Probe fileId={7} />, {
      routes: { "GET /api/v1/files/7/plates": json({ state: "pending", plates: [] }) },
    });
    await screen.findByText("pending:");
    await waitFor(() => expect(socket.onmessage).not.toBeNull());
    view.route({ "GET /api/v1/files/7/plates": json(READY) });
    const notice = (kind: string) =>
      socket.onmessage?.({
        data: JSON.stringify({ type: "derivative", model_id: 3, file_id: 7, kind, state: "ready" }),
      });

    notice("thumbnail");
    notice("plates");

    await screen.findByText("ready: Main parts, Wall mount");
    expect(view.requests().filter(({ url }) => url.endsWith("/plates"))).toHaveLength(2);
  });
});
