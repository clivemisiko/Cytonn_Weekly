import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";
import type { SnipsListing } from "./types";
import { useSnips } from "./usesnips";

vi.mock("./api", () => ({ uploadSnip: vi.fn(), readSnip: vi.fn(), getSnips: vi.fn() }));

const EMPTY = { sectors: [{ id: "land", label: "Land" }], snips: [], max_per_sector: 6 } as unknown as SnipsListing;
const file = (name: string) => new File(["fake"], name, { type: "image/png" });
const files = (...names: string[]) => names.map(file) as unknown as FileList;

/** A promise the test settles itself, so it can look at the state while an upload is still being sent. */
function held<T>() {
  let settle!: { ok: (v: T) => void; fail: (e: Error) => void };
  const promise = new Promise<T>((ok, fail) => (settle = { ok, fail }));
  return { promise, ...settle };
}

describe("useSnips: an upload in progress names its file, and clears on success and on failure", () => {
  // A function returned from beforeEach is run as the test's teardown, so the braces keep the mock from being called again.
  beforeEach(() => {
    vi.mocked(api.uploadSnip).mockReset();
  });

  it("shows the file and its sector while it is sent, then clears once the server answers", async () => {
    const answer = held<SnipsListing>();
    vi.mocked(api.uploadSnip).mockReturnValue(answer.promise);
    const snips = useSnips("2027-01-08");
    const going = snips.upload("land", files("fake-snip.png"));
    expect(snips.uploading.value).toBe(true);
    expect(snips.uploadingFile.value).toEqual({ sector: "land", name: "fake-snip.png" });
    answer.ok(EMPTY);
    await going;
    expect(snips.uploading.value).toBe(false);
    expect(snips.uploadingFile.value).toBeNull();
    expect(snips.error.value).toBeNull();
  });

  it("says a refusal with the file's name and leaves nothing in progress", async () => {
    const answer = held<SnipsListing>();
    vi.mocked(api.uploadSnip).mockReturnValue(answer.promise);
    const snips = useSnips("2027-01-08");
    const going = snips.upload("land", files("fake-bad.png"));
    expect(snips.uploadingFile.value?.name).toBe("fake-bad.png");
    answer.fail(new Error("Fake refusal."));
    await expect(going).resolves.toBeUndefined(); // said, never thrown: SnipSector.vue does not catch
    expect(snips.uploading.value).toBe(false);
    expect(snips.uploadingFile.value).toBeNull();
    expect(snips.error.value).toBe("fake-bad.png: Fake refusal.");
  });

  it("clears the spinner even when the refusal is not an error object", async () => {
    // reading .message of it once threw inside the catch, and the in-progress state was never cleared
    const answer = held<SnipsListing>();
    vi.mocked(api.uploadSnip).mockReturnValue(answer.promise);
    const snips = useSnips("2027-01-08");
    const going = snips.upload("land", files("fake-odd.png"));
    answer.fail(undefined as unknown as Error);
    await expect(going).resolves.toBeUndefined();
    expect(snips.uploading.value).toBe(false);
    expect(snips.uploadingFile.value).toBeNull();
    expect(snips.error.value).toBe("fake-odd.png: the upload failed.");
  });
});
