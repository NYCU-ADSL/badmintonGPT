// Message TTS — markdown → spoken-prose extraction + segmentation.
// [badmintonGPT — see docs/MESSAGE_TTS.md / patches/webui-tts.patch]
//
// The speaker button must read only plain prose aloud: no code, charts, tables, math, or media.
// We parse the raw markdown with the same remark stack the renderer uses (so "what's spoken"
// matches "what's prose on screen"), then walk the mdast and keep prose-bearing nodes while
// dropping the rest. Output is split into short, sentence-bounded segments so each one fits in a
// GET query string (the gateway TTS proxy is GET-only) and the first segment can start playing
// quickly.

import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

/** Minimal structural view of an mdast node — avoids depending on plugin-specific type unions
 *  (remark-gfm tables, remark-math math) being present in @types/mdast. */
interface MdNode {
  type: string;
  value?: string;
  children?: MdNode[];
}

/** Node types whose entire subtree is non-prose and must not be spoken. */
const SKIP_TYPES = new Set<string>([
  "code", // fenced code blocks (incl. ```visualizer charts)
  "inlineCode", // `inline code`
  "math", // $$ block math $$ (remark-math)
  "inlineMath", // inline math (remark-math)
  "table", // GFM tables (remark-gfm) — drop rows/cells with them
  "html", // raw HTML / <video> / <iframe> / <details> …
  "image",
  "imageReference",
  "thematicBreak", // ---
  "yaml", // frontmatter
  "toml",
  "definition", // [id]: url link-reference definitions
  "footnoteDefinition",
  "footnoteReference",
]);

/** Block-level node types that should end with a sentence boundary so segmentation can split. */
const BLOCK_TYPES = new Set<string>([
  "paragraph",
  "heading",
  "listItem",
  "blockquote",
  "tableRow",
]);

const parser = unified()
  .use(remarkParse)
  .use(remarkGfm)
  .use(remarkMath, { singleDollarTextMath: false });

function walk(node: MdNode, out: string[]): void {
  if (SKIP_TYPES.has(node.type)) return;
  if (node.type === "text") {
    if (node.value) out.push(node.value);
    return;
  }
  if (node.type === "break") {
    out.push("\n");
    return;
  }
  if (node.children) {
    for (const child of node.children) walk(child, out);
  }
  // For links/linkReferences we keep the visible label (the children) and drop the URL, which
  // lives on node.url — never pushed here.
  if (BLOCK_TYPES.has(node.type)) out.push("\n");
}

function normalize(text: string): string {
  return text
    .replace(/[ \t\r\f\v]+/g, " ")
    .replace(/ *\n */g, "\n")
    .replace(/\n{2,}/g, "\n")
    .trim();
}

/** Extract the spoken-prose text of a markdown reply, dropping code/charts/tables/math/media. */
export function markdownToSpeechText(markdown: string): string {
  if (!markdown.trim()) return "";
  let tree: MdNode;
  try {
    tree = parser.parse(markdown) as unknown as MdNode;
  } catch {
    return "";
  }
  const out: string[] = [];
  walk(tree, out);
  return normalize(out.join(""));
}

// Fallback segment size, used only when the bootstrap omits `tts.max_segment_chars`. The live value
// is server-driven (TTS_SEGMENT_CHARS → bootstrap → useTtsSettings → segmentForTts). Kept small
// because the TTS proxy is non-streaming: the first sound can't play until the whole first segment
// is synthesized, and synthesis is ~linear in chars (~0.1 s/char), so smaller = lower latency.
const DEFAULT_SEGMENT_CHARS = 60;
// Split after sentence-ending punctuation (CJK + ASCII) and hard breaks, keeping the delimiter.
const SENTENCE_RE = /[^。．！？!?；;\n]*[。．！？!?；;\n]+|[^。．！？!?；;\n]+$/g;

/** Split spoken text into ordered segments, each <= maxChars, for the chunked GET requests. */
export function segmentForTts(text: string, maxChars: number = DEFAULT_SEGMENT_CHARS): string[] {
  const trimmed = text.trim();
  if (!trimmed) return [];
  const sentences = trimmed.match(SENTENCE_RE) ?? [trimmed];
  const segments: string[] = [];
  let buf = "";
  const flush = () => {
    const s = buf.trim();
    if (s) segments.push(s);
    buf = "";
  };
  for (const raw of sentences) {
    let sentence = raw;
    // A single sentence longer than the budget is hard-split.
    while (sentence.length > maxChars) {
      flush();
      segments.push(sentence.slice(0, maxChars).trim());
      sentence = sentence.slice(maxChars);
    }
    if (buf.length + sentence.length > maxChars) flush();
    buf += sentence;
  }
  flush();
  return segments;
}
