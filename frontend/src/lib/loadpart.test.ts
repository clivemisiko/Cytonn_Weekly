import { describe, expect, it, vi } from "vitest";
import { usePart } from "./loadpart";

describe("usePart", () => {
  it("keeps what one read got when another read fails, and Try again repeats only the failed one", async () => {
    const readiness = vi.fn().mockResolvedValue({ ready: true });
    const form = vi.fn().mockRejectedValueOnce(new Error("The server did not answer within 30 seconds.")).mockResolvedValue({ fake: "form" });
    const first = usePart(readiness);
    const second = usePart(form);
    expect(await first.run()).toBe(true);
    expect(await second.run()).toBe(false);
    expect(first.value.value).toEqual({ ready: true });
    expect(second.problem.value).toBe("The server did not answer within 30 seconds.");

    expect(await second.run()).toBe(true);
    expect(second.problem.value).toBeNull();
    expect(second.value.value).toEqual({ fake: "form" });
    expect(readiness).toHaveBeenCalledTimes(1);
    expect(form).toHaveBeenCalledTimes(2);
  });

  it("drops an answer that a reset or a newer run overtook", async () => {
    let finish: (v: string) => void = () => {};
    const part = usePart(() => new Promise<string>((r) => (finish = r)));
    const stale = part.run();
    part.reset();
    finish("old week");
    expect(await stale).toBe(false);
    expect(part.value.value).toBeNull();
  });

  it("does not show a failure that a reset overtook", async () => {
    let fail: (e: Error) => void = () => {};
    const part = usePart(() => new Promise<string>((_, r) => (fail = r)));
    const stale = part.run();
    part.reset();
    fail(new Error("too late"));
    expect(await stale).toBe(false);
    expect(part.problem.value).toBeNull();
  });
});
