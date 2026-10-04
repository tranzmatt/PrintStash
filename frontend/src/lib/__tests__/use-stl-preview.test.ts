/** STL preparation is polled as status; terminal failures never become STL bytes. */
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { stlPreviewMessage, useStlPreview } from "../use-stl-preview";

describe("useStlPreview", () => {
  const request = vi.fn<typeof fetch>();
  beforeEach(() => {
    vi.stubGlobal("fetch", request);
    request.mockReset();
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:preview");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("waits for prepared bytes", async () => {
    vi.useFakeTimers();
    request
      .mockResolvedValueOnce(new Response(JSON.stringify({ state: "pending" }), { status: 202 }))
      .mockResolvedValueOnce(new Response(new Blob(["stl"])));
    const { result } = renderHook(() => useStlPreview("/api/v1/files/1/stl"));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(result.current).toEqual({ state: "ready", url: "blob:preview" });
    expect(request).toHaveBeenCalledTimes(2);
  });

  it("stops polling a terminal failure", async () => {
    request.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "resource_limit" }), { status: 422 }),
    );
    const { result } = renderHook(() => useStlPreview("/api/v1/files/1/stl"));

    await waitFor(() =>
      expect(result.current).toEqual({ state: "failed", reason: "resource_limit" }),
    );

    expect(request).toHaveBeenCalledTimes(1);
  });

  it("releases the browser preview", async () => {
    request.mockResolvedValueOnce(new Response(new Blob(["stl"])));
    const { result, unmount } = renderHook(() => useStlPreview("/api/v1/files/1/stl"));
    await waitFor(() => expect(result.current.state).toBe("ready"));

    unmount();

    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:preview");
  });

  it("aborts a pending load on unmount", () => {
    request.mockImplementation(() => new Promise(() => {}));
    const { unmount } = renderHook(() => useStlPreview("/api/v1/files/1/stl"));

    unmount();

    expect(request.mock.calls[0][1]?.signal?.aborted).toBe(true);
  });
});

describe("stlPreviewMessage", () => {
  it("shows memory refusal", () => {
    expect(stlPreviewMessage("resource_limit")).toBe("3D preview omitted due to memory limits");
  });
});
