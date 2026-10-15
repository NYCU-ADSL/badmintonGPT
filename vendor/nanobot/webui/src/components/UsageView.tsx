/**
 * [badmintonGPT fork] Usage page — the signed-in account's quota, spend and breakdown.
 *
 * Backed by ``GET /api/usage`` (NANOBOT_ACCOUNTS). Whitelisted accounts are unlimited; everyone
 * else has a lifetime allowance that covers chat-model tokens and paid MCP jobs (reels).
 */
import { ChevronLeft, Clapperboard, Loader2, Menu, MessageSquareText, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import type { UsagePayload } from "@/lib/types";
import { cn } from "@/lib/utils";

interface UsageViewProps {
  usage: UsagePayload | null;
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
  onBackToChat: () => void;
  onToggleSidebar: () => void;
}

function usd(value: number | null | undefined, digits = 2): string {
  const v = typeof value === "number" && Number.isFinite(value) ? value : 0;
  // Sub-cent spend is common (one short reply ≈ $0.01); show it instead of "$0.00".
  if (v > 0 && v < 0.01) return `$${v.toFixed(4)}`;
  return `$${v.toFixed(digits)}`;
}

function compact(n: number, locale: string): string {
  return new Intl.NumberFormat(locale, { notation: "compact", maximumFractionDigits: 1 }).format(n);
}

function serverLabel(server: string, t: (k: string, o?: Record<string, unknown>) => string): string {
  if (server.includes("reels")) return t("usage.servers.reels");
  return server;
}

export function UsageView({
  usage,
  loading,
  error,
  onRefresh,
  onBackToChat,
  onToggleSidebar,
}: UsageViewProps) {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage || "en";
  const unlimited = !!usage?.unlimited;
  const quota = usage?.quota_usd ?? null;
  const spent = usage?.spent_usd ?? 0;
  const remaining = usage?.remaining_usd ?? null;
  const left = remaining ?? (quota != null ? Math.max(0, quota - spent) : 0);
  const leftPct = quota && quota > 0 ? Math.max(0, Math.min(100, (left / quota) * 100)) : 0;
  const llm = usage?.breakdown?.llm;
  const jobs = usage?.breakdown?.jobs ?? [];
  const daily = usage?.breakdown?.daily ?? [];
  const dailyMax = Math.max(0.0001, ...daily.map((d) => d.cost_usd));

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-background">
      <header className="flex h-12 shrink-0 items-center gap-1 px-3 lg:hidden">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={t("thread.header.toggleSidebar", { defaultValue: "Toggle sidebar" })}
          onClick={onToggleSidebar}
          className="h-8 w-8 rounded-full"
        >
          <Menu className="h-4 w-4" />
        </Button>
      </header>
      <main className="min-w-0 flex-1 overflow-y-auto [scrollbar-gutter:stable]">
        <div className="mx-auto w-full max-w-[860px] px-4 py-6 sm:px-8 lg:py-12">
          <button
            type="button"
            onClick={onBackToChat}
            className="mb-4 inline-flex w-fit items-center gap-1.5 rounded-full px-2.5 py-1.5 text-[12px] font-medium text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground"
          >
            <ChevronLeft className="h-3.5 w-3.5" aria-hidden />
            {t("settings.backToChat")}
          </button>
          <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
            <div className="min-w-0">
              <h1 className="text-[28px] font-semibold leading-tight tracking-[-0.02em] text-foreground sm:text-[32px]">
                {t("usage.title")}
              </h1>
              {usage?.email ? (
                <p className="mt-1 truncate text-[13px] text-muted-foreground">{usage.email}</p>
              ) : null}
            </div>
            <Button
              type="button"
              variant="ghost"
              onClick={onRefresh}
              disabled={loading}
              className="h-8 gap-1.5 rounded-full px-3 text-[12.5px] text-muted-foreground"
            >
              <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} aria-hidden />
              {t("usage.refresh")}
            </Button>
          </div>

          {error && !usage ? (
            <div className="rounded-2xl border border-destructive/25 bg-destructive/5 px-4 py-3 text-[13px] text-destructive">
              {error}
            </div>
          ) : !usage ? (
            <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              {t("settings.status.loading")}
            </div>
          ) : !usage.enabled ? (
            <div className="rounded-2xl border border-border/60 bg-card/70 px-5 py-4 text-[13px] text-muted-foreground">
              {t("usage.disabled")}
            </div>
          ) : (
            <div className="space-y-5">
              <section
                aria-label={t("usage.balance")}
                className="rounded-[22px] border border-border/55 bg-card/80 p-5 shadow-[0_18px_60px_rgba(15,23,42,0.06)] sm:p-6"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className={cn(
                      "rounded-full px-2.5 py-0.5 text-[11.5px] font-semibold",
                      unlimited
                        ? "bg-brand/15 text-brand"
                        : usage.exhausted
                          ? "bg-destructive/12 text-destructive"
                          : "bg-muted text-muted-foreground",
                    )}
                  >
                    {unlimited
                      ? t("usage.plan.unlimited")
                      : usage.exhausted
                        ? t("usage.plan.exhausted")
                        : t("usage.plan.quota", { quota: usd(quota) })}
                  </span>
                </div>
                {unlimited ? (
                  <div className="mt-4">
                    <p className="text-[13px] text-muted-foreground">{t("usage.spentTotal")}</p>
                    <p className="mt-1 text-[34px] font-semibold tabular-nums tracking-[-0.02em]">
                      {usd(spent)}
                    </p>
                    <p className="mt-1 text-[12.5px] text-muted-foreground">{t("usage.unlimitedHint")}</p>
                  </div>
                ) : (
                  <div className="mt-4">
                    <p className="text-[13px] text-muted-foreground">{t("usage.remaining")}</p>
                    <p
                      className={cn(
                        "mt-1 text-[34px] font-semibold tabular-nums tracking-[-0.02em]",
                        usage.exhausted && "text-destructive",
                      )}
                    >
                      {usd(remaining)}
                      <span className="ml-2 text-[15px] font-medium text-muted-foreground">
                        / {usd(quota)}
                      </span>
                    </p>
                    <div
                      role="progressbar"
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={Math.round(leftPct)}
                      aria-label={t("usage.remainingOf", { remaining: usd(left), quota: usd(quota) })}
                      className="mt-4 h-2.5 w-full overflow-hidden rounded-full bg-muted"
                    >
                      <div
                        className={cn(
                          "h-full rounded-full transition-[width] duration-500",
                          leftPct <= 0 ? "bg-destructive" : leftPct <= 20 ? "bg-amber-500" : "bg-brand",
                        )}
                        style={{ width: `${leftPct}%` }}
                      />
                    </div>
                    {usage.exhausted ? (
                      <p className="mt-3 text-[13px] text-destructive">{t("usage.exhaustedHint")}</p>
                    ) : null}
                  </div>
                )}
              </section>

              <div className="grid gap-4 sm:grid-cols-2">
                <section className="rounded-[18px] border border-border/55 bg-card/70 p-5">
                  <div className="flex items-center gap-2 text-[13px] font-semibold">
                    <MessageSquareText className="h-4 w-4 text-muted-foreground" aria-hidden />
                    {t("usage.llm.title")}
                  </div>
                  <p className="mt-3 text-[24px] font-semibold tabular-nums">{usd(llm?.cost_usd)}</p>
                  <dl className="mt-3 grid grid-cols-2 gap-y-1.5 text-[12.5px]">
                    <dt className="text-muted-foreground">{t("usage.llm.calls")}</dt>
                    <dd className="text-right tabular-nums">{compact(llm?.calls ?? 0, locale)}</dd>
                    <dt className="text-muted-foreground">{t("usage.llm.input")}</dt>
                    <dd className="text-right tabular-nums">{compact(llm?.prompt_tokens ?? 0, locale)}</dd>
                    <dt className="text-muted-foreground">{t("usage.llm.cached")}</dt>
                    <dd className="text-right tabular-nums">{compact(llm?.cached_tokens ?? 0, locale)}</dd>
                    <dt className="text-muted-foreground">{t("usage.llm.output")}</dt>
                    <dd className="text-right tabular-nums">{compact(llm?.completion_tokens ?? 0, locale)}</dd>
                  </dl>
                </section>
                <section className="rounded-[18px] border border-border/55 bg-card/70 p-5">
                  <div className="flex items-center gap-2 text-[13px] font-semibold">
                    <Clapperboard className="h-4 w-4 text-muted-foreground" aria-hidden />
                    {t("usage.jobs.title")}
                  </div>
                  <p className="mt-3 text-[24px] font-semibold tabular-nums">
                    {usd(jobs.reduce((acc, j) => acc + j.cost_usd, 0))}
                  </p>
                  {jobs.length === 0 ? (
                    <p className="mt-3 text-[12.5px] text-muted-foreground">{t("usage.jobs.none")}</p>
                  ) : (
                    <dl className="mt-3 grid grid-cols-2 gap-y-1.5 text-[12.5px]">
                      {jobs.map((j) => (
                        <div key={j.server} className="contents">
                          <dt className="text-muted-foreground">
                            {serverLabel(j.server, t)} · {t("usage.jobs.count", { count: j.count })}
                          </dt>
                          <dd className="text-right tabular-nums">{usd(j.cost_usd)}</dd>
                        </div>
                      ))}
                    </dl>
                  )}
                </section>
              </div>

              {daily.length > 0 ? (
                <section className="rounded-[18px] border border-border/55 bg-card/70 p-5">
                  <h2 className="text-[13px] font-semibold">{t("usage.daily")}</h2>
                  <ul className="mt-3 space-y-1.5">
                    {daily.map((d) => (
                      <li key={d.day} className="grid grid-cols-[5.5rem_1fr_4.5rem] items-center gap-3 text-[12.5px]">
                        <span className="tabular-nums text-muted-foreground">{d.day}</span>
                        <span className="h-1.5 overflow-hidden rounded-full bg-muted">
                          <span
                            className="block h-full rounded-full bg-brand/80"
                            style={{ width: `${Math.max(2, (d.cost_usd / dailyMax) * 100)}%` }}
                          />
                        </span>
                        <span className="text-right tabular-nums">{usd(d.cost_usd)}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}

              <p className="px-1 text-[12px] leading-5 text-muted-foreground">
                {usage.pricing
                  ? t("usage.pricingNote", {
                      model: usage.pricing.model,
                      input: usage.pricing.input,
                      cached: usage.pricing.cached_input,
                      output: usage.pricing.output,
                    })
                  : null}{" "}
                {t("usage.updateNote")}
              </p>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
