import { describe, expect, it } from "vitest";
import { createSSRApp, h } from "vue";
import { renderToString } from "vue/server-renderer";
import CountTile from "@/components/review/CountTile.vue";

const render = (props: InstanceType<typeof CountTile>["$props"]) => renderToString(createSSRApp({ render: () => h(CountTile, props) }));

describe("CountTile", () => {
  it("is a plain tile without `pressed` (the run view)", async () => {
    const html = await render({ status: "flagged", value: 3 });
    expect(html.startsWith("<div")).toBe(true);
    expect(html).not.toContain("aria-pressed");
  });
  it("is a toggle button on the review's strip, pressed or not", async () => {
    for (const pressed of [true, false]) {
      const html = await render({ status: "clean", value: 0, sub: "None in this draft", pressed });
      expect(html.startsWith('<button type="button"')).toBe(true);
      expect(html).toContain(`aria-pressed="${pressed}"`);
    }
  });
});
