import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { currentLocale, setAppLanguage } from "@/i18n";
import { localeOption, type SupportedLocale } from "@/i18n/config";
import { redeemInvite } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { AccountInfo } from "@/lib/types";

/** The gate replaces the whole app (and so the Settings language picker), so it carries its own
 * switch between the two languages the invite copy is written in. */
const GATE_LOCALES: SupportedLocale[] = ["zh-TW", "en"];

/** [badmintonGPT fork] Shown instead of the app while the signed-in account still needs an
 * invite code (NANOBOT_ACCOUNTS_INVITE_REQUIRED). The gateway checks the code and refuses turns
 * until it is redeemed, so this screen is a convenience, not the gate itself. */
export function InviteGate({
  token,
  email,
  onActivated,
  onLogout,
}: {
  token: string;
  email: string;
  onActivated: (account: AccountInfo) => void;
  onLogout: () => void;
}) {
  const { t } = useTranslation();
  const [code, setCode] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [waitUntil, setWaitUntil] = useState(0);
  const [now, setNow] = useState(() => Date.now());

  const waitS = Math.max(0, Math.ceil((waitUntil - now) / 1000));
  useEffect(() => {
    if (waitUntil <= Date.now()) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [waitUntil]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const value = code.trim();
    if (!value || submitting || waitS > 0) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await redeemInvite(token, value);
      if (result.ok) {
        onActivated(result.account);
        return;
      }
      if (result.retryAfterS > 0) {
        setNow(Date.now());
        setWaitUntil(Date.now() + result.retryAfterS * 1000);
      }
      setError(result.reason === "full" ? "full" : result.reason === "cooldown" ? null : "invalid");
    } catch {
      setError("failed");
    } finally {
      setSubmitting(false);
    }
  };

  const locale = currentLocale();

  return (
    <div className="relative flex h-full w-full items-center justify-center px-6">
      <div
        role="group"
        aria-label={t("sidebar.language.label")}
        className="absolute right-4 top-4 flex rounded-full border border-border p-0.5 text-xs"
      >
        {GATE_LOCALES.map((code) => (
          <button
            key={code}
            type="button"
            lang={code}
            aria-pressed={locale === code}
            onClick={() => void setAppLanguage(code)}
            className={cn(
              "rounded-full px-3 py-1 transition-colors",
              locale === code
                ? "bg-foreground text-background"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {localeOption(code).nativeLabel}
          </button>
        ))}
      </div>
      <form onSubmit={handleSubmit} className="flex w-full max-w-sm flex-col gap-4">
        <div className="flex flex-col items-center gap-2 text-center">
          <img
            src="/brand/mark-green.svg"
            alt=""
            className="mb-2 h-12 w-12 select-none object-contain"
            draggable={false}
          />
          <h1 className="text-lg font-semibold">{t("app.invite.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("app.invite.hint")}</p>
        </div>
        <Input
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder={t("app.invite.placeholder")}
          aria-label={t("app.invite.placeholder")}
          maxLength={64}
          autoComplete="off"
          disabled={submitting}
          autoFocus
        />
        <Button
          type="submit"
          className="w-full bg-brand text-brand-foreground hover:bg-brand/90"
          disabled={!code.trim() || submitting || waitS > 0}
        >
          {submitting ? t("app.invite.checking") : t("app.invite.submit")}
        </Button>
        <p role="status" aria-live="polite" className="min-h-5 text-center text-sm text-destructive">
          {waitS > 0
            ? t("app.invite.cooldown", { seconds: waitS })
            : error
              ? t(`app.invite.${error}`)
              : null}
        </p>
        <div className="flex flex-col items-center gap-1 text-xs text-muted-foreground">
          <span>{t("app.invite.signedInAs", { email })}</span>
          <button type="button" onClick={onLogout} className="underline-offset-2 hover:underline">
            {t("app.invite.switchAccount")}
          </button>
        </div>
      </form>
    </div>
  );
}
