"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ArrowSquareOutIcon } from "@phosphor-icons/react";
import { cn } from "cn";
import { Textarea } from "@/components/ui/textarea";
import { KIND_LABELS, RESOLUTION_CHIPS, STATUS_META, pyRepr, resolutionKey } from "@/lib/format";
import type { Flag, Resolution, ReviewItem } from "@/lib/types";
import { ResolutionControl } from "./resolution-control";

const EASE = [0.23, 1, 0.32, 1] as const;

const CHIP_STYLE = {
  none: "border-border text-muted-foreground",
  accept: "border-ok/40 bg-ok/10 text-ok-fg",
  fix_needed: "border-flag/40 bg-flag/10 text-flag-fg",
} as const;

function FlagDetail({ flag }: { flag: Flag }) {
  const cells: [string, string][] = [
    ["Drafted", pyRepr(flag.drafted)],
    ["Expected (normalized source)", flag.expected ?? "None"],
    ["Source value", pyRepr(flag.source_value)],
  ];
  return (
    <div className="space-y-2">
      <p className="text-sm">
        <strong className="font-semibold text-flag-fg">{flag.kind}</strong>
        <span className="text-muted-foreground"> in </span>
        {flag.message}
      </p>
      {(flag.drafted !== null || flag.expected !== null) && (
        <dl className="grid gap-2 sm:grid-cols-3">
          {cells.map(([k, v]) => (
            <div key={k} className="min-w-0 rounded-sm border bg-card px-3 py-2">
              <dt className="text-xs text-muted-foreground">{k}</dt>
              <dd className="mt-1 font-mono text-sm font-medium [overflow-wrap:anywhere]">{v}</dd>
            </div>
          ))}
        </dl>
      )}
      {flag.sources.length > 0 && (
        <ul className="space-y-1 text-xs text-muted-foreground">
          {flag.sources.map((s) => (
            <li key={s.source}>
              {s.source}: <span className="font-mono">{String(s.value)}</span> (normalized{" "}
              <span className="font-mono">{String(s.normalized)}</span>)
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Detail({ item }: { item: ReviewItem }) {
  const ctx = item.context;
  const safeUrl = ctx.url && /^https?:\/\//.test(ctx.url) ? ctx.url : null;
  return (
    <div className="space-y-3">
      {item.status === "flagged" && Array.isArray(item.detail) && item.detail.map((f, i) => <FlagDetail key={i} flag={f} />)}
      {ctx.text && <blockquote className="border-l-2 border-input pl-3 text-sm text-foreground/85">{ctx.text}</blockquote>}
      {safeUrl && (
        <p className="text-sm">
          Source:{" "}
          <a
            href={safeUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-link underline decoration-link/40 underline-offset-2 hover:decoration-link"
          >
            {ctx.title || safeUrl}
            <ArrowSquareOutIcon weight="bold" className="ml-1 inline size-4 align-[-3px]" aria-hidden />
          </a>
        </p>
      )}
      {ctx.cited_text && <p className="text-xs text-muted-foreground">Cited text: “{ctx.cited_text}”</p>}
      {item.status === "not_auto_verified" && typeof item.detail === "string" && (
        <p className="text-xs text-muted-foreground">{item.detail}</p>
      )}
    </div>
  );
}

export function ReviewItemCard({
  item,
  locked,
  onResolve,
}: {
  item: ReviewItem;
  locked: boolean;
  onResolve: (index: number, resolution: Resolution, note?: string) => Promise<boolean>;
}) {
  const meta = STATUS_META[item.status];
  const serverNote = item.resolution_note ?? "";

  // What the control shows while its write is in flight, so a click answers at once.  Writes are
  // queued in order; only the newest write's completion clears this, so rapid clicks do not flicker.
  const [pending, setPending] = useState<Resolution | undefined>(undefined);
  const latest = useRef(0);
  const shown = pending !== undefined ? pending : item.resolution;

  // The note box is the coordinator's own until it is committed; a server refresh must not overwrite typing.
  const [note, setNote] = useState(serverNote);
  const [dirty, setDirty] = useState(false);
  const [seenServerNote, setSeenServerNote] = useState(serverNote);
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault(); // a typed note is only saved when the box is left
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  if (serverNote !== seenServerNote) {
    setSeenServerNote(serverNote);
    if (!dirty) setNote(serverNote);
  }

  const resolve = (next: Resolution) => {
    const mine = ++latest.current;
    setPending(next);
    void onResolve(item.index, next).finally(() => {
      if (latest.current === mine) setPending(undefined);
    });
  };

  const commitNote = () => {
    if (!dirty) return;
    setDirty(false);
    if (note.trim() === serverNote.trim()) return;
    const mine = ++latest.current;
    setPending(shown);
    void onResolve(item.index, shown, note).finally(() => {
      if (latest.current === mine) setPending(undefined);
    });
  };

  const chipKey = resolutionKey(shown);
  const hasDetail = item.status === "flagged" || item.status === "not_auto_verified" || Object.keys(item.context).length > 0;

  return (
    <li className={cn("surface-state space-y-3 p-4", `state-${item.status}`)} data-status={item.status} data-index={item.index}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span
          className={cn(
            "inline-flex items-center gap-1 rounded-full border py-0.5 pr-2 pl-0.5 text-xs font-semibold whitespace-nowrap text-(--hue-fg)",
            item.status === "not_auto_verified" ? "border-dashed" : "",
          )}
          style={{ borderColor: "color-mix(in srgb, var(--hue) 55%, transparent)", background: "color-mix(in srgb, var(--hue) 10%, transparent)" }}
        >
          <span className="glyph size-4 text-xs" aria-hidden>
            {meta.glyph}
          </span>
          {meta.label}
        </span>
        <span className="text-sm font-semibold">{item.ref}</span>
        <span className="text-xs text-muted-foreground">{KIND_LABELS[item.kind] ?? item.kind}</span>
        <span className="relative ml-auto">
          <AnimatePresence mode="popLayout" initial={false}>
            <motion.span
              key={chipKey}
              initial={{ opacity: 0, y: 4, scale: 0.96 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, transition: { duration: 0.1 } }}
              transition={{ duration: 0.16, ease: EASE }}
              className={cn("block rounded-sm border px-2 py-0.5 text-xs font-medium", CHIP_STYLE[chipKey])}
            >
              {RESOLUTION_CHIPS[chipKey]}
            </motion.span>
          </AnimatePresence>
        </span>
      </div>

      {hasDetail && <Detail item={item} />}

      <div className="flex flex-wrap items-center gap-2">
        <ResolutionControl
          id={String(item.index)}
          label={item.ref}
          value={shown}
          disabled={locked}
          onChange={resolve}
        />
        <Textarea
          rows={1}
          name={`note-${item.index}`}
          autoComplete="off"
          value={note}
          readOnly={locked}
          aria-label={`Note for ${item.ref}`}
          placeholder="Add a note (optional)…"
          maxLength={2000}
          onChange={(e) => {
            setNote(e.target.value);
            setDirty(true);
          }}
          onBlur={commitNote}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              e.currentTarget.blur(); // commit through onBlur
            }
          }}
          className={cn("min-w-48 flex-1 resize-none text-sm md:text-sm", locked && "bg-muted text-muted-foreground")}
        />
      </div>
    </li>
  );
}
