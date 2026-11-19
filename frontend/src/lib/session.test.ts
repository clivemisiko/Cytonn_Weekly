import { afterEach, describe, expect, it, vi } from "vitest";
import { useReviewSession } from "./session";
import type { Review } from "./types";

const reviewWith = (statuses: string[]) =>
  ({ run_id: 7, decision: null, review_items: statuses.map((status, index) => ({ index, status })) }) as unknown as Review;

function capture(returns: Review) {
  const calls: { url: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
    calls.push({ url, body: JSON.parse(String(init.body)) });
    return { ok: true, status: 200, json: async () => returns };
  });
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

describe("deciding a review", () => {
  it("sends how many flagged items the screen holds, so the server can check the approval", async () => {
    const calls = capture(reviewWith(["flagged", "clean", "flagged", "not_auto_verified"]));
    const session = useReviewSession(reviewWith(["flagged", "clean", "flagged", "not_auto_verified"]));
    expect(await session.decide("approved")).toBe(true);
    expect(calls).toEqual([{ url: "/api/reviews/7/decide", body: { decision: "approved", acknowledged_flagged: 2 } }]);
  });

  it("sends zero when nothing is flagged", async () => {
    const calls = capture(reviewWith(["clean"]));
    const session = useReviewSession(reviewWith(["clean", "not_auto_verified"]));
    await session.decide("approved");
    expect(calls[0].body).toEqual({ decision: "approved", acknowledged_flagged: 0 });
  });
});
