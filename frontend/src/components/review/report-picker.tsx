"use client";

import { useId, useState } from "react";
import { CaretDownIcon } from "@phosphor-icons/react";
import { cn } from "cn";
import { Button } from "@/components/ui/button";
import type { CompanionKind, ReportChoice, ReportType, ReportTypeInfo } from "@/lib/types";

const FIELD =
  "flex h-10 w-full rounded-md border border-input bg-card px-3 text-base transition-colors outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40 disabled:cursor-not-allowed disabled:bg-muted disabled:opacity-60 aria-invalid:border-flag aria-invalid:ring-3 aria-invalid:ring-flag/20 md:text-sm";

function Select({
  id,
  value,
  onChange,
  disabled,
  children,
}: {
  id: string;
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="relative">
      <select
        id={id}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className={cn(FIELD, "appearance-none pr-9")}
      >
        {children}
      </select>
      <CaretDownIcon
        weight="bold"
        className="pointer-events-none absolute top-1/2 right-3 size-3.5 -translate-y-1/2 text-muted-foreground"
        aria-hidden
      />
    </div>
  );
}

/**
 * Which report the overview shows: the weekly (the default), a quarterly, half-year or annual Markets Review, or a
 * companion research report. The period is part of every review's key, so Q3'2026 Fixed Income and a weekly Fixed
 * Income are different reviews. The API normalizes and validates the period; this only sends what was typed.
 */
export function ReportPicker({
  current,
  types,
  kinds,
  onApply,
}: {
  current: ReportChoice;
  types: ReportTypeInfo[];
  kinds: CompanionKind[];
  /** Resolves to an error message to show beside the period, or null once the overview has switched. */
  onApply: (next: ReportChoice) => Promise<string | null>;
}) {
  const id = useId();
  const [type, setType] = useState<ReportType>(current.type);
  const [period, setPeriod] = useState(current.period);
  const [kind, setKind] = useState(current.kind ?? kinds[0]?.slug ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const info = types.find((t) => t.slug === type);
  const issueOf = (slug: string) => kinds.find((k) => k.slug === slug)?.issue ?? "";
  const dirty = type !== current.type || period.trim() !== current.period || (type === "companion" && kind !== current.kind);

  const chooseType = (next: ReportType) => {
    setType(next);
    setError(null);
    const nextInfo = types.find((t) => t.slug === next);
    if (next === current.type) setPeriod(current.period);
    // A companion report has no "period just ended": it rides with the weekly issue its kind was published in.
    else if (next === "companion") setPeriod(issueOf(kind));
    else setPeriod(nextInfo?.suggested_period ?? "");
  };

  /** Another companion report: its own issue replaces the last one's, unless the coordinator typed a different one. */
  const chooseKind = (next: string) => {
    setKind(next);
    setError(null);
    if (!period.trim() || period.trim() === issueOf(kind)) setPeriod(issueOf(next));
  };

  const apply = async () => {
    setBusy(true);
    setError(null);
    const message = await onApply({ type, period: period.trim(), kind: type === "companion" ? kind : null });
    setBusy(false);
    setError(message);
  };

  const periodLabel = type === "companion" ? "Weekly issue it rides with" : info?.period_required ? "Period" : "Issue (optional)";
  const kindInfo = kinds.find((k) => k.slug === kind);
  const hint =
    type === "companion"
      ? kindInfo
        ? `${kindInfo.title} ran as the Focus of the Week of Cytonn ${kindInfo.issue} (${kindInfo.published}).`
        : ""
      : info
        ? `Structure verified against ${info.published_as}.`
        : "";
  const placeholder = info?.period_hint ?? "";

  return (
    <form
      aria-labelledby={`${id}-title`}
      className="rounded-lg border bg-card p-4 sm:p-6"
      onSubmit={(e) => {
        e.preventDefault();
        if (!busy) void apply();
      }}
    >
      <h2 id={`${id}-title`} className="eyebrow pb-3">
        Report
      </h2>
      <div
        className={cn(
          "grid grid-cols-1 items-end gap-4 sm:grid-cols-2",
          "lg:grid-cols-[minmax(0,16rem)_minmax(0,14rem)_auto]",
        )}
      >
        <div className="space-y-1">
          <label htmlFor={`${id}-type`} className="text-sm font-semibold">
            Report type
          </label>
          <Select id={`${id}-type`} value={type} onChange={(v) => chooseType(v as ReportType)} disabled={busy}>
            {types.map((t) => (
              <option key={t.slug} value={t.slug}>
                {t.title}
              </option>
            ))}
          </Select>
        </div>

        {type === "companion" && (
          // Its own full-width row: the reports' titles are long, and a native select cannot wrap them.
          <div className="space-y-1 sm:col-span-2 lg:col-span-full lg:row-start-2">
            <label htmlFor={`${id}-kind`} className="text-sm font-semibold">
              Which report
            </label>
            <Select id={`${id}-kind`} value={kind} onChange={chooseKind} disabled={busy}>
              {kinds.map((k) => (
                <option key={k.slug} value={k.slug}>
                  {k.title}
                </option>
              ))}
            </Select>
          </div>
        )}

        <div className="space-y-1">
          <label htmlFor={`${id}-period`} className="text-sm font-semibold">
            {periodLabel}
          </label>
          <input
            id={`${id}-period`}
            name="period"
            type="text"
            autoComplete="off"
            spellCheck={false}
            maxLength={40}
            value={period}
            disabled={busy}
            onChange={(e) => {
              setPeriod(e.target.value);
              setError(null);
            }}
            placeholder={placeholder}
            aria-invalid={error ? true : undefined}
            aria-describedby={`${id}-hint`}
            className={cn(FIELD, "font-mono")}
          />
        </div>

        <Button type="submit" size="lg" variant={dirty ? "default" : "outline"} disabled={busy} className="sm:col-span-2 lg:col-span-1 lg:justify-self-start">
          {busy ? "Loading…" : "Show sections"}
        </Button>
      </div>
      <p id={`${id}-hint`} role={error ? "alert" : undefined} className={cn("pt-2 text-xs", error ? "font-semibold text-flag-fg" : "text-muted-foreground")}>
        {error ?? hint}
      </p>
    </form>
  );
}
