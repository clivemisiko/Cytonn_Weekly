"use client";

import { useCallback, useEffect, useState } from "react";
import { CheckIcon, FileIcon, PlusIcon, QuestionIcon, TrashIcon, WarningIcon } from "@phosphor-icons/react";
import { cn } from "cn";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import * as api from "@/lib/api";
import { friendlyDate, friendlyTime } from "@/lib/format";
import type { AnalystColumn, AnalystField, AnalystForm, AnalystRow, AnalystTable } from "@/lib/types";
import { Notice } from "./banners";
import { FIELD } from "./inputs-panel";

type Origin = "typed" | "differs" | "workbook" | "empty";

const ORIGIN = {
  typed: { Icon: CheckIcon, box: "border-ok/40 bg-ok/10 text-ok-fg" },
  differs: { Icon: WarningIcon, box: "border-warn/40 bg-warn/10 text-warn-fg" },
  workbook: { Icon: FileIcon, box: "border-input bg-muted text-foreground" },
  empty: { Icon: QuestionIcon, box: "border-dashed border-input text-muted-foreground" },
} as const;

/** Where an item's value comes from: typed here, the uploaded workbook, both and different, or nowhere. By shape as well as colour. */
function OriginChip({ origin, children }: { origin: Origin; children: React.ReactNode }) {
  const { Icon, box } = ORIGIN[origin];
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold whitespace-nowrap", box)}>
      <Icon weight="bold" className="size-3" aria-hidden />
      {children}
    </span>
  );
}

const range = (min: number | null, max: number | null, unit: string) =>
  min === null || max === null ? "" : `${min.toLocaleString()} to ${max.toLocaleString()}${unit === "%" || unit === "x" ? unit : unit ? ` ${unit}` : ""}`;

/** Source, where it is printed and the range the API accepts: the same three facts under every item. */
function Provenance({ source, usedIn, expected }: { source: string; usedIn: string; expected?: string }) {
  return (
    <p className="text-xs text-muted-foreground">
      Source: <span className="font-medium text-foreground">{source}</span>
      <span aria-hidden> · </span>
      Used in: {usedIn}
      {expected && (
        <>
          <span aria-hidden> · </span>
          Expected: <span className="font-mono">{expected}</span>
        </>
      )}
    </p>
  );
}

function Differences({ lines }: { lines: string[] }) {
  if (lines.length === 0) return null;
  return (
    <Notice tone="warn" role="status">
      <ul className="space-y-1">
        {lines.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      <p className="mt-1 font-medium">The reviewer is shown each difference.</p>
    </Notice>
  );
}

const asText = (value: string | string[] | null | undefined) => (Array.isArray(value) ? value.join("\n") : (value ?? ""));

/** One typed field. It is saved when the cursor leaves it; emptied, the workbook's value (if any) is used again. */
function FieldRow({
  item,
  disabled,
  onSave,
  onDirty,
}: {
  item: AnalystField;
  disabled: boolean;
  onSave: (value: string) => void;
  onDirty: (dirty: boolean) => void;
}) {
  const saved = asText(item.value);
  const [value, setValue] = useState(saved);
  const fromBook = asText(item.workbook?.value);
  const origin: Origin = saved ? (item.differences.length ? "differs" : "typed") : fromBook ? "workbook" : "empty";
  const id = `analyst-${item.key}`;
  const change = (next: string) => {
    setValue(next);
    onDirty(next.trim() !== saved);
  };
  const commit = () => {
    if (value.trim() !== saved) onSave(value);
  };
  const shared = {
    id,
    value,
    disabled,
    onBlur: commit,
    "aria-describedby": `${id}-hint`,
  };
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor={id} className="text-sm font-semibold">
          {item.label}
        </label>
        <OriginChip origin={origin}>
          {origin === "typed" ? "Typed" : origin === "differs" ? "Typed, differs from the workbook" : origin === "workbook" ? "From the workbook" : "Empty"}
        </OriginChip>
      </div>
      {item.kind === "names" ? (
        <Textarea
          {...shared}
          rows={4}
          onChange={(e) => change(e.target.value)}
          placeholder={fromBook || "Safaricom\nEquity Group\n…"}
          className="py-2 font-mono"
        />
      ) : (
        <div className="flex items-center gap-2">
          <input
            {...shared}
            type={item.kind === "date" ? "date" : "text"}
            inputMode={item.kind === "number" ? "decimal" : undefined}
            autoComplete="off"
            onChange={(e) => change(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") e.currentTarget.blur();
            }}
            placeholder={fromBook ? `${fromBook} (workbook)` : undefined}
            className={cn(FIELD, "w-44 font-mono tabular-nums")}
          />
          {item.unit && <span className="text-sm text-muted-foreground">{item.unit}</span>}
          {item.kind === "date" && !value && fromBook && (
            <span className="text-xs text-muted-foreground">
              Workbook: <span className="font-mono">{friendlyDate(fromBook)}</span>
            </span>
          )}
        </div>
      )}
      <div id={`${id}-hint`} className="space-y-1">
        {item.help && <p className="text-xs text-muted-foreground">{item.help}</p>}
        <Provenance source={item.source} usedIn={item.used_in} expected={range(item.min, item.max, item.unit)} />
        {origin === "workbook" && item.workbook && (
          <p className="text-xs text-muted-foreground">
            Read from <span className="font-mono [overflow-wrap:anywhere]">{item.workbook.ref}</span>. Type a value to use yours instead.
          </p>
        )}
        {item.workbook_note && !saved && <p className="text-xs text-warn-fg">{item.workbook_note}</p>}
      </div>
      <Differences lines={item.differences} />
    </div>
  );
}

const header = (col: AnalystColumn) => (col.unit ? `${col.label} (${col.unit})` : col.label);

/** The rows in use, read-only: what was typed, else what the uploaded workbook holds. */
function RowsPreview({ item, rows }: { item: AnalystTable; rows: AnalystRow[] }) {
  return (
    <div className="max-h-56 overflow-auto rounded-md border" tabIndex={0} role="region" aria-label={`${item.label}: rows in use`}>
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-muted text-left">
          <tr>
            {item.columns.map((c) => (
              <th key={c.key} scope="col" className={cn("px-2 py-1 font-semibold", c.kind !== "text" && "text-right")}>
                {header(c)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, n) => (
            <tr key={n} className="border-t">
              {item.columns.map((c) => (
                <td key={c.key} className={cn("px-2 py-1", c.kind !== "text" && "text-right font-mono tabular-nums")}>
                  {row[c.key] ?? ""}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TableHead({ item, origin, count }: { item: AnalystTable; origin: Origin; count: number }) {
  const rows = `${count} row${count === 1 ? "" : "s"}`;
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="text-sm font-semibold">{item.label}</h4>
        <OriginChip origin={origin}>
          {origin === "typed"
            ? `Typed, ${rows}`
            : origin === "differs"
              ? `Typed, ${rows}, differs from the workbook`
              : origin === "workbook"
                ? `From the workbook, ${rows}`
                : "Empty"}
        </OriginChip>
      </div>
      {item.help && <p className="max-w-[72ch] text-xs text-muted-foreground">{item.help}</p>}
      <Provenance source={item.source} usedIn={item.used_in} />
    </div>
  );
}

function TableNotes({ item, typed }: { item: AnalystTable; typed: boolean }) {
  return (
    <>
      {!typed && item.workbook_ref && (
        <p className="text-xs text-muted-foreground">
          Read from <span className="font-mono">{item.workbook_ref}</span>. Type here to use yours instead.
        </p>
      )}
      {item.workbook_note && !typed && <p className="text-xs text-warn-fg">{item.workbook_note}</p>}
      {item.warnings.map((w) => (
        <Notice key={w} tone="warn" role="status">
          {w}
        </Notice>
      ))}
      <Differences lines={item.differences} />
    </>
  );
}

const tableOrigin = (item: AnalystTable): Origin =>
  item.rows?.length ? (item.differences.length ? "differs" : "typed") : item.workbook_rows?.length ? "workbook" : "empty";

/** A table pasted as lines (rank, fund, rate). The API reads the lines; this shows the rows it kept. */
function PasteTable({
  item,
  disabled,
  onSave,
  onDirty,
}: {
  item: AnalystTable;
  disabled: boolean;
  onSave: (text: string | null) => void;
  onDirty: (dirty: boolean) => void;
}) {
  const [text, setText] = useState(item.text);
  const dirty = text.trim() !== item.text.trim();
  const typed = !!item.rows?.length;
  const rows = item.rows ?? item.workbook_rows ?? [];
  const id = `analyst-${item.key}`;
  return (
    <div className="space-y-2">
      <TableHead item={item} origin={tableOrigin(item)} count={rows.length} />
      <label htmlFor={id} className="sr-only">
        {item.label}: paste the rows
      </label>
      <Textarea
        id={id}
        rows={4}
        value={text}
        disabled={disabled}
        spellCheck={false}
        onChange={(e) => {
          setText(e.target.value);
          onDirty(e.target.value.trim() !== item.text.trim());
        }}
        placeholder={`${item.columns.map((c) => c.label).join("   ")}\n${item.example}`}
        className="max-h-56 overflow-auto py-2 font-mono whitespace-pre"
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" disabled={disabled || !dirty || !text.trim()} onClick={() => onSave(text)}>
          Save table
        </Button>
        {dirty && (
          <Button
            size="sm"
            variant="outline"
            disabled={disabled}
            onClick={() => {
              setText(item.text);
              onDirty(false);
            }}
          >
            Discard changes
          </Button>
        )}
        {typed && !dirty && (
          <Button size="sm" variant="outline" disabled={disabled} onClick={() => onSave(null)}>
            <TrashIcon weight="bold" data-icon="inline-start" aria-hidden />
            Clear typed table
          </Button>
        )}
        {dirty && <span className="text-xs font-medium text-warn-fg">Not saved yet.</span>}
      </div>
      {rows.length > 0 && <RowsPreview item={item} rows={rows} />}
      <TableNotes item={item} typed={typed} />
    </div>
  );
}

interface Line {
  /** A given row's key, or a local id for a row of the open-ended grid. */
  id: string;
  label: string;
  typed: AnalystRow;
  book: AnalystRow;
}

const nameKey = (name: string) => name.trim().replace(/\s+/g, " ").toLowerCase();

/** The grid's lines: the given rows, or the typed rows followed by the workbook's other rows. */
function linesOf(item: AnalystTable): Line[] {
  const typed = item.rows ?? [];
  const book = item.workbook_rows ?? [];
  if (item.fixed_rows.length) {
    return item.fixed_rows.map((r) => ({
      id: r.key,
      label: r.label,
      typed: { ...(typed.find((t) => t.row === r.key) ?? {}) },
      book: book.find((b) => b.row === r.key) ?? {},
    }));
  }
  const name = item.columns[0].key;
  const lines: Line[] = typed.map((t, n) => ({
    id: `typed-${n}`,
    label: t[name] ?? "",
    typed: { ...t },
    book: book.find((b) => nameKey(b[name] ?? "") === nameKey(t[name] ?? "")) ?? {},
  }));
  const seen = new Set(typed.map((t) => nameKey(t[name] ?? "")));
  book.forEach((b, n) => {
    if (!seen.has(nameKey(b[name] ?? ""))) lines.push({ id: `book-${n}`, label: b[name] ?? "", typed: {}, book: b });
  });
  return lines;
}

/** The rows a grid sends: only what was typed. A workbook row nobody touched is not sent; the workbook supplies it. */
function rowsOf(item: AnalystTable, lines: Line[]): AnalystRow[] {
  const fixed = item.fixed_rows.length > 0;
  const name = item.columns[0].key;
  const out: AnalystRow[] = [];
  for (const line of lines) {
    const row: AnalystRow = {};
    for (const col of item.columns) {
      const value = (line.typed[col.key] ?? "").trim();
      if (value) row[col.key] = value;
    }
    if (fixed) {
      if (Object.keys(row).length) out.push({ row: line.id, ...row });
      continue;
    }
    const company = row[name] ?? (Object.keys(row).length ? (line.book[name] ?? "") : "");
    if (company) out.push({ ...row, [name]: company });
  }
  return out;
}

const canonical = (item: AnalystTable, rows: AnalystRow[]) =>
  JSON.stringify(rows.map((r) => ["row", ...item.columns.map((c) => c.key)].map((k) => r[k] ?? "")));

/** A grid typed cell by cell: the Universe of Coverage's inputs, the Eurobond issues. Empty cells show the workbook's value. */
function GridTable({
  item,
  disabled,
  onSave,
  onDirty,
}: {
  item: AnalystTable;
  disabled: boolean;
  onSave: (rows: AnalystRow[] | null) => void;
  onDirty: (dirty: boolean) => void;
}) {
  const [lines, setLines] = useState(() => linesOf(item));
  const fixed = item.fixed_rows.length > 0;
  const name = item.columns[0];
  const columns = fixed ? item.columns : item.columns.slice(1);
  const saved = canonical(item, item.rows ?? []);
  const dirty = canonical(item, rowsOf(item, lines)) !== saved;
  const typedCount = item.rows?.length ?? 0;
  const count = fixed ? typedCount || (item.workbook_rows?.length ?? 0) : lines.filter((l) => l.label || Object.keys(l.typed).length).length;

  const update = (next: Line[]) => {
    setLines(next);
    onDirty(canonical(item, rowsOf(item, next)) !== saved);
  };
  const setCell = (id: string, key: string, value: string) =>
    update(lines.map((l) => (l.id === id ? { ...l, typed: { ...l.typed, [key]: value } } : l)));

  return (
    <div className="space-y-2">
      <TableHead item={item} origin={tableOrigin(item)} count={count} />
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full text-xs">
          <thead className="bg-muted text-left">
            <tr>
              <th scope="col" className="px-2 py-2 font-semibold">
                {fixed ? "" : header(name)}
              </th>
              {columns.map((c) => (
                <th key={c.key} scope="col" className="px-2 py-2 font-semibold">
                  {header(c)}
                </th>
              ))}
              {!fixed && <th scope="col" className="w-8" />}
            </tr>
          </thead>
          <tbody>
            {lines.map((line) => {
              const fromBook = !fixed && Object.keys(line.book).length > 0;
              const rowName = fixed ? line.label : line.typed[name.key] || line.book[name.key] || "new company";
              return (
                <tr key={line.id} className="border-t align-middle">
                  <th scope="row" className="px-2 py-1 text-left font-medium">
                    {fixed || fromBook ? (
                      <span className="whitespace-nowrap">{line.label}</span>
                    ) : (
                      <input
                        type="text"
                        autoComplete="off"
                        aria-label={`${item.label}: ${name.label}`}
                        value={line.typed[name.key] ?? ""}
                        disabled={disabled}
                        onChange={(e) => setCell(line.id, name.key, e.target.value)}
                        placeholder="Company"
                        className={cn(FIELD, "h-8 w-40 px-2 text-sm md:text-xs")}
                      />
                    )}
                  </th>
                  {columns.map((c) => (
                    <td key={c.key} className="px-2 py-1">
                      <input
                        type={c.kind === "date" ? "date" : "text"}
                        inputMode={c.kind === "number" ? "decimal" : undefined}
                        autoComplete="off"
                        aria-label={`${rowName}: ${header(c)}`}
                        value={line.typed[c.key] ?? ""}
                        disabled={disabled}
                        onChange={(e) => setCell(line.id, c.key, e.target.value)}
                        placeholder={line.book[c.key] ?? ""}
                        className={cn(FIELD, "h-8 px-2 font-mono text-sm tabular-nums md:text-xs", c.kind === "date" ? "w-36" : "w-24")}
                      />
                    </td>
                  ))}
                  {!fixed && (
                    <td className="px-1">
                      {!fromBook && (
                        <button
                          type="button"
                          disabled={disabled}
                          aria-label={`Remove ${rowName}`}
                          onClick={() => update(lines.filter((l) => l.id !== line.id))}
                          className="grid size-8 place-items-center rounded-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
                        >
                          <TrashIcon weight="bold" className="size-4" aria-hidden />
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              );
            })}
            {lines.length === 0 && (
              <tr className="border-t">
                <td colSpan={columns.length + 2} className="px-2 py-3 text-muted-foreground">
                  No company yet. Add one, or upload the workbook to start from its rows.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {!fixed && (
          <Button
            size="sm"
            variant="outline"
            disabled={disabled}
            onClick={() => update([...lines, { id: `new-${Date.now()}-${lines.length}`, label: "", typed: {}, book: {} }])}
          >
            <PlusIcon weight="bold" data-icon="inline-start" aria-hidden />
            Add company
          </Button>
        )}
        <Button size="sm" disabled={disabled || !dirty} onClick={() => onSave(rowsOf(item, lines))}>
          Save
        </Button>
        {dirty && (
          <Button size="sm" variant="outline" disabled={disabled} onClick={() => update(linesOf(item))}>
            Discard changes
          </Button>
        )}
        {typedCount > 0 && !dirty && (
          <Button size="sm" variant="outline" disabled={disabled} onClick={() => onSave(null)}>
            <TrashIcon weight="bold" data-icon="inline-start" aria-hidden />
            Clear typed values
          </Button>
        )}
        {dirty && <span className="text-xs font-medium text-warn-fg">Not saved yet.</span>}
      </div>
      {(item.workbook_rows?.length ?? 0) > 0 && (
        <p className="text-xs text-muted-foreground">
          Grey figures are the uploaded workbook’s. A cell you type overrides it; a cell you leave empty uses it.
        </p>
      )}
      <TableNotes item={item} typed={typedCount > 0} />
    </div>
  );
}

/**
 * "Weekly analyst inputs": the figures only the analysts hold, typed for one report week when no workbook is sent. The
 * API owns the form (fields, units, ranges, source labels) and checks every value; this renders what it returns and
 * shows a refusal in its words. An uploaded workbook prefills each item, a typed value overrides it, and any difference
 * is listed here and again for the reviewer. Derived figures are never typed: the draft works them out.
 */
export function AnalystPanel({
  week,
  section,
  disabled,
  refresh,
  onPending,
}: {
  /** The Friday the report week ends on (ISO date). */
  week: string;
  /** The section whose inputs are shown: "fixed_income" or "equities". */
  section: string;
  disabled?: boolean;
  /** Changes when the week's uploads change, so the workbook's values are read again. */
  refresh: number;
  /** True while something typed here is not saved yet (the draft button waits for it). */
  onPending: (pending: boolean) => void;
}) {
  const [form, setForm] = useState<AnalystForm | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState<Record<string, boolean>>({});

  useEffect(() => {
    let live = true;
    api
      .getAnalystInputs(week, section)
      .then((f) => live && setForm(f))
      .catch((err: Error) => live && setError(err.message));
    return () => {
      live = false;
    };
  }, [week, section, refresh]);

  const pending = busy || Object.values(dirty).some(Boolean);
  useEffect(() => onPending(pending), [pending, onPending]);
  useEffect(() => () => onPending(false), [onPending]);

  const mark = useCallback((key: string, value: boolean) => setDirty((d) => (d[key] === value ? d : { ...d, [key]: value })), []);

  const save = async (key: string, changes: api.AnalystChanges) => {
    setBusy(true);
    setError(null);
    try {
      setForm(await api.saveAnalystInputs(week, section, changes));
      mark(key, false);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const locked = busy || !!disabled;
  const hasBook = form?.workbooks[section] ?? false;
  return (
    <section aria-labelledby="analyst-title" className="space-y-4 rounded-lg border bg-card p-6">
      <div className="space-y-1 border-b pb-4">
        <h2 id="analyst-title" className="text-lg font-semibold">
          Weekly analyst inputs
        </h2>
        <p className="max-w-[72ch] text-sm text-muted-foreground">
          The figures only the analysts hold, for the week ending <span className="font-mono">{friendlyDate(week)}</span>. Type them
          here when no workbook is sent. Every value is carried into the draft as an analyst input for you to check; none is
          suggested or filled in, and anything left empty is marked as missing in the draft.
        </p>
        {form && (
          <p className="text-xs text-muted-foreground">
            {hasBook
              ? "A workbook is uploaded for this week: its values are shown and used wherever you type nothing."
              : "No workbook is uploaded for this week: the draft uses only what is typed here."}
            {form.saved_at ? ` Last saved ${friendlyTime(form.saved_at)}.` : ""}
          </p>
        )}
      </div>

      {error && (
        <Notice role="alert" className="font-medium whitespace-pre-line">
          {error}
        </Notice>
      )}

      {form === null && !error ? (
        <p className="text-sm text-muted-foreground" aria-busy="true">
          Reading the form…
        </p>
      ) : (
        // An item is keyed on what the API holds for it: one whose save was refused keeps what was typed, one that was
        // kept re-reads it, and saving one item never resets another that is still being typed.
        form?.groups.map((group) => (
          <section key={group.key} aria-labelledby={`analyst-group-${group.key}`} className="space-y-4 border-t pt-4 first-of-type:border-t-0 first-of-type:pt-0">
            <h3 id={`analyst-group-${group.key}`} className="eyebrow">
              {group.title}
            </h3>
            {group.items.map((item) =>
              item.type === "field" ? (
                <FieldRow
                  key={`${item.key}:${asText(item.value)}`}
                  item={item}
                  disabled={locked}
                  onDirty={(d) => mark(item.key, d)}
                  onSave={(value) => void save(item.key, { fields: { [item.key]: value.trim() || null } })}
                />
              ) : item.mode === "paste" ? (
                <PasteTable
                  key={`${item.key}:${item.text}`}
                  item={item}
                  disabled={locked}
                  onDirty={(d) => mark(item.key, d)}
                  onSave={(text) => void save(item.key, { tables: { [item.key]: text === null ? null : { text } } })}
                />
              ) : (
                <GridTable
                  key={`${item.key}:${JSON.stringify([item.rows, item.workbook_rows])}`}
                  item={item}
                  disabled={locked}
                  onDirty={(d) => mark(item.key, d)}
                  onSave={(rows) => void save(item.key, { tables: { [item.key]: rows === null ? null : { rows } } })}
                />
              ),
            )}
          </section>
        ))
      )}
    </section>
  );
}
