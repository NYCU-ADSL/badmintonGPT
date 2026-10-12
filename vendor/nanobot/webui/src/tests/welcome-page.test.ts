import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

// public/welcome.html is served to signed-out visitors (Cloudflare Access bypasses only that
// path), so it cannot load /brand/* and inlines the brand SVGs as data URIs instead. Keep those
// copies byte-identical to the files the WebUI itself shows.
const publicDir = path.resolve(__dirname, "../../public");
const welcome = readFileSync(path.join(publicDir, "welcome.html"), "utf8");

function dataUri(file: string): string {
  const bytes = readFileSync(path.join(publicDir, "brand", file));
  return `data:image/svg+xml;base64,${bytes.toString("base64")}`;
}

describe("welcome.html brand assets", () => {
  it.each([
    "lockup-horizontal.svg",
    "lockup-horizontal-dark.svg",
    "mark-small-noframe-green.svg",
  ])("inlines an up-to-date copy of %s", (file) => {
    expect(welcome).toContain(`"${dataUri(file)}"`);
  });

  it("references no other same-origin asset", () => {
    expect(welcome).not.toMatch(/(?:src|href)="\/(?!\?login")/);
  });
});
