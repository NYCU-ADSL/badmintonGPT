import { AlertTriangle, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { StreamError } from "@/lib/nanobot-client";

interface StreamErrorNoticeProps {
  error: StreamError;
  onDismiss: () => void;
}

/**
 * Dismissible banner that surfaces transport-level faults the user needs to
 * know about. Rendered above the composer so the message the fault referred
 * to remains in view just above. ``role="alert"`` + ``aria-live="assertive"``
 * ensures screen readers announce the failure.
 */
export function StreamErrorNotice({ error, onDismiss }: StreamErrorNoticeProps) {
  const { t } = useTranslation();

  const { title, body } = resolveCopy(error, t);

  return (
    <div
      role="alert"
      aria-live="assertive"
      className={cn(
        "mb-2 flex items-start gap-2 rounded-lg border border-destructive/30",
        "bg-destructive/10 px-3 py-2 text-[12px] leading-5 text-destructive",
        "animate-in fade-in-0 slide-in-from-bottom-1",
      )}
    >
      <AlertTriangle
        className="mt-0.5 h-4 w-4 shrink-0"
        aria-hidden
      />
      <div className="flex-1">
        <p className="font-medium">{title}</p>
        <p className="mt-0.5 text-destructive/80">{body}</p>
      </div>
      <Button
        variant="ghost"
        size="icon"
        onClick={onDismiss}
        aria-label={t("common.dismiss")}
        className="h-6 w-6 shrink-0 text-destructive hover:bg-destructive/15 hover:text-destructive"
      >
        <X className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}

function resolveCopy(
  error: StreamError,
  t: (key: string, options?: Record<string, unknown>) => string,
): { title: string; body: string } {
  switch (error.kind) {
    case "message_too_big":
      return {
        title: t("errors.messageTooBig.title"),
        body: t("errors.messageTooBig.body"),
      };
    case "workspace_scope_rejected":
      return {
        title: t("errors.workspaceScopeRejected.title"),
        body: t("errors.workspaceScopeRejected.body"),
      };
    case "quota_exhausted":
      return {
        title: t("errors.quotaExhausted.title"),
        body: t("errors.quotaExhausted.body", {
          quota: (error.quotaUsd ?? 0).toFixed(2),
        }),
      };
    case "off_topic":
      return { title: t("errors.offTopic.title"), body: t("errors.offTopic.body") };
    case "content_flagged":
      return error.selfHarm
        ? { title: t("errors.contentFlagged.selfHarmTitle"), body: t("errors.contentFlagged.selfHarmBody") }
        : { title: t("errors.contentFlagged.title"), body: t("errors.contentFlagged.body") };
    case "invite_required":
      return {
        title: t("errors.inviteRequired.title"),
        body: t("errors.inviteRequired.body"),
      };
    case "chat_forbidden":
      return {
        title: t("errors.chatForbidden.title"),
        body: t("errors.chatForbidden.body"),
      };
    case "command_forbidden":
      return {
        title: t("errors.commandForbidden.title"),
        body: t("errors.commandForbidden.body", { command: error.command ?? "" }),
      };
    default: {
      // Exhaustiveness guard: if a new StreamError kind is added, TS will
      // complain here until we add a corresponding i18n branch.
      const _exhaustive: never = error;
      return { title: String(_exhaustive), body: "" };
    }
  }
}
