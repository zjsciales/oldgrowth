import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useBatch } from "./useBatch.js";

const LISTINGS = [
  { id: "l1", address: "1 Test St", drives: {} },
  { id: "l2", address: "2 Test St", drives: {} },
];

function mockFetchOnce(body, ok = true) {
  global.fetch.mockResolvedValueOnce({
    ok,
    status: ok ? 200 : 400,
    statusText: ok ? "OK" : "Bad Request",
    json: async () => body,
  });
}

describe("useBatch", () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("fetches a batch for the given rater on mount", async () => {
    mockFetchOnce({ listings: LISTINGS, batch_id: "b1" });

    const { result } = renderHook(() => useBatch("zach"));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/batch?rater=zach&n=40",
      expect.objectContaining({})
    );
    expect(result.current.current).toEqual(LISTINGS[0]);
    expect(result.current.remaining).toBe(2);
  });

  it("refetches when the rater changes", async () => {
    mockFetchOnce({ listings: LISTINGS, batch_id: "b1" });
    const { result, rerender } = renderHook(({ rater }) => useBatch(rater), {
      initialProps: { rater: "zach" },
    });
    await waitFor(() => expect(result.current.loading).toBe(false));

    mockFetchOnce({ listings: [], batch_id: "b2" });
    rerender({ rater: "andrea" });

    await waitFor(() =>
      expect(global.fetch).toHaveBeenCalledWith(
        "/api/batch?rater=andrea&n=40",
        expect.objectContaining({})
      )
    );
  });

  it("judge() posts a judgment and advances the queue", async () => {
    mockFetchOnce({ listings: LISTINGS, batch_id: "b1" });
    const { result } = renderHook(() => useBatch("zach"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    mockFetchOnce({ id: 1 });
    await act(async () => {
      await result.current.judge("yes", ["mature_canopy"], []);
    });

    const [, options] = global.fetch.mock.calls[1];
    const body = JSON.parse(options.body);
    expect(body).toEqual({
      rater_id: "zach", listing_id: "l1", mode: "swipe", verdict: "yes",
      session_id: "b1", tags: ["mature_canopy"],
    });
    expect(body.anchor_ids).toBeUndefined(); // omitted, not sent as [] -- UI_SPEC.md §6
    expect(result.current.remaining).toBe(1);
    expect(result.current.current).toEqual(LISTINGS[1]);
  });

  it("judge() includes anchor_ids when provided", async () => {
    mockFetchOnce({ listings: LISTINGS, batch_id: "b1" });
    const { result } = renderHook(() => useBatch("zach"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    mockFetchOnce({ id: 1 });
    await act(async () => {
      await result.current.judge("yes", ["well_placed"], [3]);
    });

    const [, options] = global.fetch.mock.calls[1];
    const body = JSON.parse(options.body);
    expect(body.anchor_ids).toEqual([3]);
  });
});
