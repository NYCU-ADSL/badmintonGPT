import {
  ChartColumn,
  Clapperboard,
  Database,
  Gauge,
  ScanSearch,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";

/** [badmintonGPT fork] One example question per feature, listed below the composer of an empty
 * chat, one per row. Picking one only fills the input; the user still presses send. The
 * questions are the ones public/welcome.html demonstrates, so each is known to get a real answer.
 * The list scrolls on its own and shrinks with the screen height, so on a phone it never pushes
 * the greeting above the composer off screen. */
const EXAMPLES: { key: string; icon: LucideIcon }[] = [
  { key: "data", icon: Database },
  { key: "reel", icon: Clapperboard },
  { key: "chart", icon: ChartColumn },
  { key: "analysis", icon: Gauge },
  { key: "search", icon: ScanSearch },
];

interface ExamplePromptsProps {
  onPick: (prompt: string) => void;
  className?: string;
}

export function ExamplePrompts({ onPick, className }: ExamplePromptsProps) {
  const { t } = useTranslation();
  const label = t("thread.empty.examples.label");
  return (
    <div className={cn("mx-auto w-full max-w-[58rem]", className)}>
      <p className="mb-2 px-1 text-left text-xs font-medium text-muted-foreground">{label}</p>
      <ul
        aria-label={label}
        className={cn(
          "flex max-h-[max(7.5rem,min(17rem,calc(100dvh-29rem)))] flex-col gap-1.5 overflow-y-auto overscroll-contain pr-0.5",
          "scrollbar-thin [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full",
          "[&::-webkit-scrollbar-thumb]:bg-muted-foreground/30 [&::-webkit-scrollbar-track]:bg-transparent",
        )}
      >
        {EXAMPLES.map(({ key, icon: Icon }) => {
          const prompt = t(`thread.empty.examples.${key}.prompt`);
          return (
            <li key={key} className="shrink-0">
              <button
                type="button"
                onClick={() => onPick(prompt)}
                className={cn(
                  "flex w-full flex-col gap-0.5 rounded-xl border border-black/[0.05] bg-card/90 px-3.5 py-2.5 text-left",
                  "sm:flex-row sm:items-start sm:gap-3",
                  "transition-colors duration-150 hover:border-brand/40 hover:bg-card",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  "dark:border-white/[0.1] dark:bg-background/90 dark:hover:bg-background",
                )}
              >
                <span className="flex h-5 shrink-0 items-center gap-1.5 text-[12px] font-medium text-brand sm:w-[9.5rem]">
                  <Icon aria-hidden className="h-3.5 w-3.5 shrink-0" />
                  <span className="truncate">{t(`thread.empty.examples.${key}.title`)}</span>
                </span>
                <span className="min-w-0 text-[13.5px] leading-5 text-foreground/80">{prompt}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
