import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useThemeValue } from "@/hooks/useTheme";
import { notifyVisualizerSendPrompt } from "@/lib/visualizer-events";
import { cn } from "@/lib/utils";

interface VisualWidgetProps {
  code: string;
  className?: string;
}

/**
 * Shown in place of a ```visualizer fence while the message is still streaming —
 * the raw HTML/JS never appears on screen; the card swaps to the live VisualWidget
 * once the turn ends.
 */
export function VisualPlaceholder({ className }: { className?: string }) {
  const { t } = useTranslation();
  return (
    <div
      className={cn(
        "my-3 rounded-lg border border-border/60 bg-muted/30 p-4",
        className,
      )}
    >
      <div className="mb-3 flex items-center gap-2 text-[12px] text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" aria-hidden />
        <span>{t("visualizer.generating", "Generating visualization…")}</span>
      </div>
      <div className="space-y-2" aria-hidden>
        <div className="h-3 w-3/4 animate-pulse rounded bg-muted-foreground/15" />
        <div className="h-3 w-1/2 animate-pulse rounded bg-muted-foreground/15" />
        <div className="h-24 animate-pulse rounded-md bg-muted-foreground/10" />
      </div>
    </div>
  );
}

/**
 * Renders a ```visualizer fence (skills/visualise output) as a live document in an
 * iframe, following the skill's references/client-implementation.md recipe: theme
 * CSS + SVG utility classes injected ahead of the model-generated HTML/SVG/JS,
 * auto-height via ResizeObserver, and a `sendPrompt(text)` bridge back to the chat.
 * Intentionally unrestricted (allow-same-origin, no CSP) so CDN-loaded chart libs
 * just work — per project decision the visualizer is not security-hardened.
 */
export default function VisualWidget({ code, className }: VisualWidgetProps) {
  const isDark = useThemeValue() === "dark";
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const observerRef = useRef<ResizeObserver | null>(null);
  const timerRef = useRef<number | null>(null);
  const [height, setHeight] = useState(200);

  const srcDoc = useMemo(
    () =>
      `<!doctype html><html><head><meta charset="utf-8">` +
      `<style>${getThemeCSS(isDark)}\n${SVG_CLASSES}${isDark ? DARK_RAMP_OVERRIDES : ""}</style>` +
      `</head><body>${code}</body></html>`,
    [code, isDark],
  );

  const detachObserver = useCallback(() => {
    observerRef.current?.disconnect();
    observerRef.current = null;
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  /** Runs on every srcdoc (re)load — the previous document and its observer are gone. */
  const handleLoad = useCallback(() => {
    const iframe = iframeRef.current;
    const win = iframe?.contentWindow as
      | (Window & { sendPrompt?: (text: string) => void; openLink?: (url: string) => void })
      | null
      | undefined;
    const doc = iframe?.contentDocument;
    if (!iframe || !win || !doc) return;

    win.sendPrompt = (text) => notifyVisualizerSendPrompt(String(text));
    win.openLink = (url) => window.open(String(url), "_blank", "noopener");

    setHeight(Math.max(48, Math.ceil(doc.documentElement?.scrollHeight ?? 0) || 200));

    detachObserver();
    if (doc.body && typeof ResizeObserver !== "undefined") {
      const ro = new ResizeObserver(([entry]) => {
        if (timerRef.current !== null) window.clearTimeout(timerRef.current);
        timerRef.current = window.setTimeout(() => {
          timerRef.current = null;
          setHeight(Math.max(48, Math.ceil(entry.contentRect.height) + 16));
        }, 50);
      });
      ro.observe(doc.body);
      observerRef.current = ro;
    }
  }, [detachObserver]);

  useEffect(() => detachObserver, [detachObserver]);

  return (
    <div className={cn("my-3 overflow-hidden rounded-lg", className)}>
      <iframe
        ref={iframeRef}
        title="visualization"
        sandbox="allow-scripts allow-same-origin"
        srcDoc={srcDoc}
        onLoad={handleLoad}
        style={{ width: "100%", height, border: "none", display: "block", overflow: "hidden" }}
      />
    </div>
  );
}

/** Design tokens from skills/visualise references/client-implementation.md. */
function getThemeCSS(isDark: boolean): string {
  return isDark
    ? `
    :root {
      --color-text-primary: #E5E7EB;
      --color-text-secondary: #9CA3AF;
      --color-text-tertiary: #6B7280;
      --color-text-info: #60A5FA;
      --color-text-success: #34D399;
      --color-text-warning: #FBBF24;
      --color-text-danger: #F87171;
      /* Surfaces transparent so cards/metric boxes blend with the chat background. */
      --color-background-primary: transparent;
      --color-background-secondary: transparent;
      --color-background-tertiary: transparent;
      --color-border-tertiary: rgba(255,255,255,0.15);
      --color-border-secondary: rgba(255,255,255,0.3);
      --font-sans: system-ui, -apple-system, sans-serif;
      --font-mono: 'SF Mono', Menlo, monospace;
      --border-radius-md: 8px; --border-radius-lg: 12px;
    }`
    : `
    :root {
      --color-text-primary: #1F2937;
      --color-text-secondary: #6B7280;
      --color-text-tertiary: #9CA3AF;
      --color-text-info: #2563EB;
      --color-text-success: #059669;
      --color-text-warning: #D97706;
      --color-text-danger: #DC2626;
      /* Surfaces transparent so cards/metric boxes blend with the chat background. */
      --color-background-primary: transparent;
      --color-background-secondary: transparent;
      --color-background-tertiary: transparent;
      --color-border-tertiary: rgba(0,0,0,0.15);
      --color-border-secondary: rgba(0,0,0,0.3);
      --font-sans: system-ui, -apple-system, sans-serif;
      --font-mono: 'SF Mono', Menlo, monospace;
      --border-radius-md: 8px; --border-radius-lg: 12px;
    }`;
}

/** SVG text/shape/color-ramp utility classes from the same recipe (verbatim). */
const SVG_CLASSES = `
  .t { font: 400 14px var(--font-sans); fill: var(--color-text-primary); }
  .ts { font: 400 12px var(--font-sans); fill: var(--color-text-secondary); }
  .th { font: 500 14px var(--font-sans); fill: var(--color-text-primary); }
  .box { fill: var(--color-background-secondary); stroke: var(--color-border-tertiary); }
  .node { cursor: pointer; } .node:hover { opacity: 0.85; }
  .arr { stroke: var(--color-border-secondary); stroke-width: 1.5; fill: none; }
  .leader { stroke: var(--color-text-tertiary); stroke-width: 0.5; stroke-dasharray: 3 2; fill: none; }

  .c-purple > rect, .c-purple > circle, .c-purple > ellipse { fill: #EEEDFE; stroke: #534AB7; }
  .c-purple > .th { fill: #3C3489; } .c-purple > .ts { fill: #534AB7; }
  .c-teal > rect, .c-teal > circle, .c-teal > ellipse { fill: #E1F5EE; stroke: #0F6E56; }
  .c-teal > .th { fill: #085041; } .c-teal > .ts { fill: #0F6E56; }
  .c-coral > rect, .c-coral > circle, .c-coral > ellipse { fill: #FAECE7; stroke: #993C1D; }
  .c-coral > .th { fill: #712B13; } .c-coral > .ts { fill: #993C1D; }
  .c-gray > rect, .c-gray > circle, .c-gray > ellipse { fill: #F1EFE8; stroke: #5F5E5A; }
  .c-gray > .th { fill: #444441; } .c-gray > .ts { fill: #5F5E5A; }
  .c-blue > rect, .c-blue > circle, .c-blue > ellipse { fill: #E6F1FB; stroke: #185FA5; }
  .c-blue > .th { fill: #0C447C; } .c-blue > .ts { fill: #185FA5; }
  .c-amber > rect, .c-amber > circle, .c-amber > ellipse { fill: #FAEEDA; stroke: #854F0B; }
  .c-amber > .th { fill: #633806; } .c-amber > .ts { fill: #854F0B; }

  @media (prefers-color-scheme: dark) {
    .c-purple > rect, .c-purple > circle, .c-purple > ellipse { fill: #3C3489; stroke: #AFA9EC; }
    .c-purple > .th { fill: #CECBF6; } .c-purple > .ts { fill: #AFA9EC; }
    .c-teal > rect, .c-teal > circle, .c-teal > ellipse { fill: #085041; stroke: #5DCAA5; }
    .c-teal > .th { fill: #9FE1CB; } .c-teal > .ts { fill: #5DCAA5; }
    .c-coral > rect, .c-coral > circle, .c-coral > ellipse { fill: #712B13; stroke: #F0997B; }
    .c-coral > .th { fill: #F5C4B3; } .c-coral > .ts { fill: #F0997B; }
    .c-gray > rect, .c-gray > circle, .c-gray > ellipse { fill: #444441; stroke: #B4B2A9; }
    .c-gray > .th { fill: #D3D1C7; } .c-gray > .ts { fill: #B4B2A9; }
    .c-blue > rect, .c-blue > circle, .c-blue > ellipse { fill: #0C447C; stroke: #85B7EB; }
    .c-blue > .th { fill: #B5D4F4; } .c-blue > .ts { fill: #85B7EB; }
    .c-amber > rect, .c-amber > circle, .c-amber > ellipse { fill: #633806; stroke: #EF9F27; }
    .c-amber > .th { fill: #FAC775; } .c-amber > .ts { fill: #EF9F27; }
  }

  button { background: transparent; border: 0.5px solid var(--color-border-secondary); border-radius: var(--border-radius-md); padding: 6px 14px; font-size: 13px; color: var(--color-text-primary); cursor: pointer; font-family: var(--font-sans); }
  button:hover { background: var(--color-background-secondary); }
  input[type="range"] { -webkit-appearance: none; height: 4px; background: var(--color-border-tertiary); border-radius: 2px; }
  input[type="range"]::-webkit-slider-thumb { -webkit-appearance: none; width: 18px; height: 18px; border-radius: 50%; background: var(--color-background-primary); border: 0.5px solid var(--color-border-secondary); cursor: pointer; }
  * { box-sizing: border-box; margin: 0; font-family: var(--font-sans); }
  html, body { background: transparent; }
  body { color: var(--color-text-primary); line-height: 1.5; }
  canvas { background: transparent; }
`;

/**
 * The WebUI theme is app-controlled (documentElement.dark), so the iframe's
 * prefers-color-scheme may disagree with it. When the app is dark, force the
 * dark color ramps unconditionally so SVG shapes match the dark token set.
 */
const DARK_RAMP_OVERRIDES = `
  .c-purple > rect, .c-purple > circle, .c-purple > ellipse { fill: #3C3489; stroke: #AFA9EC; }
  .c-purple > .th { fill: #CECBF6; } .c-purple > .ts { fill: #AFA9EC; }
  .c-teal > rect, .c-teal > circle, .c-teal > ellipse { fill: #085041; stroke: #5DCAA5; }
  .c-teal > .th { fill: #9FE1CB; } .c-teal > .ts { fill: #5DCAA5; }
  .c-coral > rect, .c-coral > circle, .c-coral > ellipse { fill: #712B13; stroke: #F0997B; }
  .c-coral > .th { fill: #F5C4B3; } .c-coral > .ts { fill: #F0997B; }
  .c-gray > rect, .c-gray > circle, .c-gray > ellipse { fill: #444441; stroke: #B4B2A9; }
  .c-gray > .th { fill: #D3D1C7; } .c-gray > .ts { fill: #B4B2A9; }
  .c-blue > rect, .c-blue > circle, .c-blue > ellipse { fill: #0C447C; stroke: #85B7EB; }
  .c-blue > .th { fill: #B5D4F4; } .c-blue > .ts { fill: #85B7EB; }
  .c-amber > rect, .c-amber > circle, .c-amber > ellipse { fill: #633806; stroke: #EF9F27; }
  .c-amber > .th { fill: #FAC775; } .c-amber > .ts { fill: #EF9F27; }
`;
