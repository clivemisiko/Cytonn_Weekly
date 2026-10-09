"use client";

import { useEffect, useState } from "react";
import { CheckIcon, DownloadSimpleIcon, QuestionIcon, WarningIcon } from "@phosphor-icons/react";
import { cn } from "cn";
import { Button } from "@/components/ui/button";
import * as api from "@/lib/api";
import type { ExportStatus } from "@/lib/types";
import { Notice } from "./banners";

const STATE_LABEL: Record<string, string> = {
  approved: "Approved",
  in_review: "In review",
  rejected: "Rejected",
  not_drafted: "Not drafted",
};

/**
 * "Export weekly report": the approved week as one Word file, in the real issue's order. Enabled only when the API says
 * every weekly section of this report is approved; until then it lists each section's state. Nothing is sent or
 * published: the file is downloaded to the coordinator.
 */
export function ExportBar({ period, refreshKey }: { period: string; refreshKey: string }) {
  const [status, setStatus] = useState<ExportStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Re-read whenever the overview's own state changes (a section approved, a draft finished).
  useEffect(() => {
    let live = true;
    api
      .getExportStatus(period)
      .then((s) => live && setStatus(s))
      .catch((err: Error) => live && setError(err.message));
    return () => {
      live = false;
    };
  }, [period, refreshKey]);

  const download = async () => {
    setBusy(true);
    setError(null);
    try {
      const { blob, name } = await api.exportWeekly(period);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = name;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (status === null && !error) return null;
  const waiting = status ? status.sections.filter((s) => s.state !== "approved") : [];
  return (
    <section aria-labelledby="export-title" className="space-y-3 rounded-lg border bg-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
        <div className="min-w-0 space-y-1">
          <h2 id="export-title" className="text-base font-semibold">
            Export weekly report
          </h2>
          <p className="text-sm text-muted-foreground">
            {status?.ready
              ? "Every section is approved. The Word file has the six sections in the issue’s order, tables, chart placeholders and each section’s summary for the CMS."
              : `Available once every section is approved: ${waiting.length} of ${status?.sections.length ?? 6} still to go.`}
          </p>
        </div>
        <Button size="lg" disabled={!status?.ready || busy} onClick={() => void download()}>
          <DownloadSimpleIcon weight="bold" data-icon="inline-start" aria-hidden />
          {busy ? "Preparing…" : "Export weekly report"}
        </Button>
      </div>
      {status && (
        <ul className="flex flex-wrap gap-2">
          {status.sections.map((s) => {
            const ok = s.state === "approved";
            const bad = s.state === "rejected";
            const Icon = ok ? CheckIcon : bad ? WarningIcon : QuestionIcon;
            return (
              <li
                key={s.slug}
                className={cn(
                  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium",
                  ok && "border-ok/40 bg-ok/10 text-ok-fg",
                  bad && "border-flag/40 bg-flag/10 text-flag-fg",
                  !ok && !bad && "border-dashed border-input text-muted-foreground",
                )}
              >
                <Icon weight="bold" className="size-3" aria-hidden />
                {s.title}: {STATE_LABEL[s.state] ?? s.state}
              </li>
            );
          })}
        </ul>
      )}
      {status?.is_dev_draft && (
        <Notice role="alert" className="font-semibold">
          {status.dev_mode_label} The export carries a DEV MODE watermark on every page and must not be sent or published (
          {status.dev_sections.join(", ")}).
        </Notice>
      )}
      {error && (
        <Notice role="alert" className="font-medium">
          {error}
        </Notice>
      )}
    </section>
  );
}
