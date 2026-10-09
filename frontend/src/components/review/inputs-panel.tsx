"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CheckIcon, CloudArrowDownIcon, QuestionIcon, TrashIcon, UploadSimpleIcon, WarningIcon } from "@phosphor-icons/react";
import { cn } from "cn";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import * as api from "@/lib/api";
import { friendlyDate } from "@/lib/format";
import type { InputFile, InputSlot, WeeklyInputs } from "@/lib/types";
import { Notice } from "./banners";

const FIELD =
  "flex h-10 rounded-md border border-input bg-card px-3 text-base transition-colors outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40 disabled:cursor-not-allowed disabled:bg-muted disabled:opacity-60 aria-invalid:border-flag md:text-sm";

const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

/** The weekday of an ISO date, read as a calendar date (no time zone shift). */
const weekdayOf = (iso: string) => WEEKDAYS[new Date(`${iso}T00:00:00Z`).getUTCDay()];

const megabytes = (bytes: number) => `${(bytes / 1_048_576).toFixed(1)} MB`;

type Tone = "ok" | "warn" | "none";

/** Received and this week's, received but dated another week, or not received: by shape as well as colour. */
function StateChip({ tone, children }: { tone: Tone; children: React.ReactNode }) {
  const Icon = tone === "ok" ? CheckIcon : tone === "warn" ? WarningIcon : QuestionIcon;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold whitespace-nowrap",
        tone === "ok" && "border-ok/40 bg-ok/10 text-ok-fg",
        tone === "warn" && "border-warn/40 bg-warn/10 text-warn-fg",
        tone === "none" && "border-dashed border-input text-muted-foreground",
      )}
    >
      <Icon weight="bold" className="size-3" aria-hidden />
      {children}
    </span>
  );
}

function FileLine({ file, onRemove, busy }: { file: InputFile; onRemove: () => void; busy: boolean }) {
  return (
    <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
      <span className="font-mono [overflow-wrap:anywhere]">{file.original_name || file.stored_name}</span>
      <span aria-hidden>·</span>
      <span>
        dated <span className="font-mono">{file.read_date ? friendlyDate(file.read_date) : "unread"}</span>
      </span>
      <span aria-hidden>·</span>
      <span className="font-mono">{megabytes(file.size)}</span>
      {file.fetched_from && (
        <>
          <span aria-hidden>·</span>
          <span>fetched from CBK</span>
        </>
      )}
      <button
        type="button"
        onClick={onRemove}
        disabled={busy}
        aria-label={`Remove ${file.original_name || file.stored_name}`}
        className="inline-flex items-center gap-1 rounded-sm text-link underline decoration-link/40 underline-offset-2 outline-none hover:decoration-link focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
      >
        <TrashIcon weight="bold" className="size-3" aria-hidden />
        Remove
      </button>
    </p>
  );
}

function Slot({
  slot,
  week,
  busy,
  onUpload,
  onRemove,
  onFetch,
}: {
  slot: InputSlot;
  week: string;
  busy: boolean;
  onUpload: (slot: string, files: File[]) => void;
  onRemove: (storedName: string) => void;
  onFetch: () => void;
}) {
  const picker = useRef<HTMLInputElement>(null);
  const file = slot.file ?? null;
  const days = slot.days ?? [];
  const got = days.filter((d) => d.received).length;
  const tone: Tone = slot.per_day
    ? got === days.length
      ? "ok"
      : got > 0
        ? "warn"
        : "none"
    : file
      ? file.matches
        ? "ok"
        : "warn"
      : "none";
  const label = slot.per_day
    ? `${got} of ${days.length} received`
    : file
      ? file.matches
        ? "Received, this week’s"
        : slot.slug === "nse_yield_curve"
          ? "Received, dated outside this week"
          : "Received, not this week’s"
      : slot.optional
        ? "Not received (optional)"
        : "Not received";
  return (
    <li className="space-y-2 border-t py-4 first:border-t-0 first:pt-0">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0 space-y-1">
          <p className="flex flex-wrap items-center gap-2 text-sm font-semibold">
            {slot.title}
            <StateChip tone={tone}>{label}</StateChip>
          </p>
          <p className="text-xs text-muted-foreground">{slot.help}</p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          {slot.fetchable && !file && (
            <Button variant="outline" size="sm" disabled={busy} onClick={onFetch}>
              <CloudArrowDownIcon weight="bold" data-icon="inline-start" aria-hidden />
              Fetch from CBK
            </Button>
          )}
          <input
            ref={picker}
            type="file"
            accept={slot.kind === "pdf" ? ".pdf,application/pdf" : ".xlsx"}
            multiple={slot.per_day}
            className="sr-only"
            tabIndex={-1}
            aria-hidden
            onChange={(e) => {
              const files = Array.from(e.target.files ?? []);
              e.target.value = ""; // the same file can be chosen again after a refusal
              if (files.length) onUpload(slot.slug, files);
            }}
          />
          <Button variant="outline" size="sm" disabled={busy} onClick={() => picker.current?.click()}>
            <UploadSimpleIcon weight="bold" data-icon="inline-start" aria-hidden />
            {slot.per_day ? "Upload reports" : file ? "Replace" : "Upload"}
            <span className="sr-only">: {slot.title}</span>
          </Button>
        </div>
      </div>
      {file && (
        <>
          <FileLine file={file} busy={busy} onRemove={() => onRemove(file.stored_name)} />
          {!file.matches && file.read_date && (
            <p className="text-xs font-medium text-warn-fg">
              The file itself is dated {friendlyDate(file.read_date)}; this week ends {friendlyDate(week)}.
              {slot.slug === "nse_yield_curve" ? " It is still shown as context, with its own date." : " Figures it does not hold for this week are left out."}
            </p>
          )}
          {file.note && <p className="text-xs text-warn-fg">{file.note}</p>}
        </>
      )}
      {slot.per_day && (
        <ul className="grid gap-2 sm:grid-cols-5">
          {days.map((d) => (
            <li
              key={d.date}
              className={cn(
                "space-y-1 rounded-md border px-2 py-2 text-xs",
                d.received ? "border-ok/40 bg-ok/10" : "border-dashed border-input",
              )}
            >
              <p className="flex items-center justify-between gap-1 font-semibold">
                {d.weekday}
                {d.received ? (
                  <CheckIcon weight="bold" className="size-3 text-ok-fg" aria-hidden />
                ) : (
                  <QuestionIcon weight="bold" className="size-3 text-muted-foreground" aria-hidden />
                )}
              </p>
              <p className="font-mono text-muted-foreground">{friendlyDate(d.date)}</p>
              {d.received && d.file ? (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => onRemove(d.file!.stored_name)}
                  className="rounded-sm text-link underline decoration-link/40 underline-offset-2 outline-none hover:decoration-link focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
                >
                  Remove<span className="sr-only"> {d.weekday}’s report</span>
                </button>
              ) : (
                <p className="text-muted-foreground">Missing</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

/**
 * "This week's inputs": the files the analysts send each Friday, uploaded here for one report week. Each file is checked
 * and read by the API before it is kept; this shows what was received, the date read from the file itself, and whether
 * that is this week. Nothing is derived here, and a refused upload shows the API's own reason.
 */
export function InputsPanel({
  week,
  onWeek,
  disabled,
}: {
  /** The Friday the report week ends on (ISO date). */
  week: string;
  /** Choose another week: the report on screen changes with it. */
  onWeek: (weekEnding: string) => void;
  disabled?: boolean;
}) {
  const [status, setStatus] = useState<WeeklyInputs | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState(week);
  const [bidding, setBidding] = useState("");
  const [previous, setPrevious] = useState("");
  const notFriday = picked && weekdayOf(picked) !== "Friday" ? `${friendlyDate(picked)} is a ${weekdayOf(picked)}; a weekly report’s week ends on a Friday.` : null;

  const show = useCallback((next: WeeklyInputs) => {
    setStatus(next);
    setBidding(next.notes.bidding_range ?? "");
    setPrevious(next.notes.previous_issue ?? "");
  }, []);

  // The start screen keys this panel on the week, so a new week starts from empty state; this only reads it.
  useEffect(() => {
    let live = true;
    api
      .getInputs(week)
      .then((s) => live && show(s))
      .catch((err: Error) => live && setError(err.message));
    return () => {
      live = false;
    };
  }, [week, show]);

  /** Run one change against the API and show what it returns; a refusal is shown in the API's words. */
  const act = async (work: () => Promise<WeeklyInputs>) => {
    setBusy(true);
    setError(null);
    try {
      show(await work());
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const upload = (slot: string, files: File[]) =>
    act(async () => {
      let last: WeeklyInputs | null = null;
      const refused: string[] = [];
      for (const file of files) {
        try {
          last = await api.uploadInput(week, slot, file);
          setStatus(last);
        } catch (err) {
          refused.push(`${file.name}: ${(err as Error).message}`);
        }
      }
      if (refused.length) setTimeout(() => setError(refused.join(" ")), 0);
      return last ?? (await api.getInputs(week));
    });

  const saveNote = (key: "bidding_range" | "previous_issue", value: string) => {
    if ((status?.notes[key] ?? "") === value.trim()) return;
    void act(() => api.saveInputNotes(week, { [key]: value }));
  };

  const locked = busy || disabled;
  return (
    <section aria-labelledby="inputs-title" className="space-y-4 rounded-lg border bg-card p-6">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3 border-b pb-4">
        <div className="space-y-1">
          <h2 id="inputs-title" className="text-lg font-semibold">
            This week’s inputs
          </h2>
          <p className="max-w-[62ch] text-sm text-muted-foreground">
            The workbooks and reports the analysts send each Friday. A part of the section whose input is missing is marked
            unavailable in the draft; no figure is ever filled in.
          </p>
        </div>
        <div className="space-y-1">
          <label htmlFor="week-ending" className="eyebrow block">
            Week ending (a Friday)
          </label>
          <div className="flex gap-2">
            <input
              id="week-ending"
              type="date"
              value={picked}
              disabled={locked}
              aria-invalid={notFriday ? true : undefined}
              aria-describedby={notFriday ? "week-ending-error" : undefined}
              onChange={(e) => setPicked(e.target.value)}
              className={cn(FIELD, "font-mono")}
            />
            <Button variant="outline" disabled={locked || !picked || !!notFriday || picked === week} onClick={() => onWeek(picked)}>
              Show this week
            </Button>
          </div>
          {notFriday && (
            <p id="week-ending-error" role="alert" className="text-xs font-medium text-flag-fg">
              {notFriday}
            </p>
          )}
        </div>
      </div>

      {error && (
        <Notice role="alert" className="font-medium">
          {error}
        </Notice>
      )}

      {status === null && !error ? (
        <p className="text-sm text-muted-foreground" aria-busy="true">
          Reading what has been received for the week ending <span className="font-mono">{friendlyDate(week)}</span>…
        </p>
      ) : (
        status && (
          <>
            <p className="text-sm">
              Week ending <span className="font-mono font-semibold">{friendlyDate(status.week_ending)}</span>: Monday{" "}
              <span className="font-mono">{friendlyDate(status.monday)}</span> to Friday.
            </p>
            <ul>
              {status.slots.map((slot) => (
                <Slot
                  key={slot.slug}
                  slot={slot}
                  week={status.week_ending}
                  busy={!!locked}
                  onUpload={(s, files) => void upload(s, files)}
                  onRemove={(name) => void act(() => api.removeInput(week, name))}
                  onFetch={() => void act(() => api.fetchBulletin(week))}
                />
              ))}
            </ul>

            <div className="space-y-4 border-t pt-4">
              <div className="space-y-1">
                <label htmlFor="bidding-range" className="text-sm font-semibold">
                  T-bond bidding range (the analysts’ recommendation)
                </label>
                <Textarea
                  id="bidding-range"
                  rows={3}
                  maxLength={2000}
                  value={bidding}
                  disabled={locked}
                  onChange={(e) => setBidding(e.target.value)}
                  onBlur={() => saveNote("bidding_range", bidding)}
                  placeholder="e.g. Our recommended bidding range for FXD1/2019/020 is 12.8% - 13.3%…"
                  aria-describedby="bidding-range-hint"
                  className="py-2"
                />
                <p id="bidding-range-hint" className="text-xs text-muted-foreground">
                  The analysts’ own call, carried as you type it. The tool never proposes a range; left empty, the draft marks
                  the range as missing.
                </p>
              </div>
              <div className="space-y-1">
                <label htmlFor="previous-issue" className="text-sm font-semibold">
                  Previous issue (optional)
                </label>
                <input
                  id="previous-issue"
                  type="text"
                  autoComplete="off"
                  value={previous}
                  disabled={locked}
                  onChange={(e) => setPrevious(e.target.value)}
                  onBlur={() => saveNote("previous_issue", previous)}
                  placeholder="https://cytonnreport.com/research/…"
                  aria-describedby="previous-issue-hint"
                  className={cn(FIELD, "w-full")}
                />
                <p id="previous-issue-hint" className="text-xs text-muted-foreground">
                  Where the carried-forward paragraphs come from. Left empty, the newest issue published by this Friday is
                  used. Carried text is always flagged for you to edit.
                </p>
              </div>
            </div>
          </>
        )
      )}
    </section>
  );
}
