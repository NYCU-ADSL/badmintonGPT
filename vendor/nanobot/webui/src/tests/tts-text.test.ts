import { describe, expect, it } from "vitest";

import { markdownToSpeechText, segmentForTts } from "@/lib/tts-text";

describe("markdownToSpeechText", () => {
  it("keeps prose, headings and list items", () => {
    const md = "# Title\n\nHello world.\n\n- one\n- two";
    const out = markdownToSpeechText(md);
    expect(out).toContain("Title");
    expect(out).toContain("Hello world.");
    expect(out).toContain("one");
    expect(out).toContain("two");
  });

  it("drops fenced code blocks", () => {
    const md = "Before.\n\n```python\nprint('secret code')\n```\n\nAfter.";
    const out = markdownToSpeechText(md);
    expect(out).toContain("Before.");
    expect(out).toContain("After.");
    expect(out).not.toContain("print");
    expect(out).not.toContain("secret code");
  });

  it("drops visualizer (chart) fences", () => {
    const md = "Chart below.\n\n```visualizer\n<svg>chart markup</svg>\n```";
    const out = markdownToSpeechText(md);
    expect(out).toContain("Chart below.");
    expect(out).not.toContain("svg");
    expect(out).not.toContain("chart markup");
  });

  it("drops inline code but keeps surrounding prose", () => {
    const out = markdownToSpeechText("Run `npm install` now.");
    expect(out).toContain("Run");
    expect(out).toContain("now.");
    expect(out).not.toContain("npm install");
  });

  it("drops GFM tables", () => {
    const md = "Stats:\n\n| Player | Wins |\n| --- | --- |\n| Axelsen | 5 |\n\nDone.";
    const out = markdownToSpeechText(md);
    expect(out).toContain("Stats:");
    expect(out).toContain("Done.");
    expect(out).not.toContain("Axelsen");
    expect(out).not.toContain("Wins");
  });

  it("drops block math", () => {
    const out = markdownToSpeechText("Result:\n\n$$ x^2 + y^2 = z^2 $$\n\nclear.");
    expect(out).toContain("Result:");
    expect(out).toContain("clear.");
    expect(out).not.toContain("x^2");
  });

  it("drops images but keeps the paragraph text", () => {
    const out = markdownToSpeechText("See ![a chart](chart.png) here.");
    expect(out).toContain("See");
    expect(out).toContain("here.");
    expect(out).not.toContain("chart.png");
  });

  it("keeps link label and drops the URL", () => {
    const out = markdownToSpeechText("Visit [the docs](https://example.com/page).");
    expect(out).toContain("the docs");
    expect(out).not.toContain("example.com");
  });

  it("returns empty for an all-code reply", () => {
    const out = markdownToSpeechText("```js\nconst a = 1;\n```");
    expect(out.trim()).toBe("");
  });
});

describe("segmentForTts", () => {
  it("returns no segments for empty text", () => {
    expect(segmentForTts("")).toEqual([]);
  });

  it("splits on sentence boundaries and never exceeds the budget", () => {
    const sentence = "句子。";
    const segments = segmentForTts(sentence.repeat(200), 40);
    expect(segments.length).toBeGreaterThan(1);
    for (const seg of segments) expect(seg.length).toBeLessThanOrEqual(40);
  });

  it("hard-splits a single oversized sentence", () => {
    const segments = segmentForTts("a".repeat(1000), 100);
    expect(segments.length).toBe(10);
    for (const seg of segments) expect(seg.length).toBeLessThanOrEqual(100);
  });
});
