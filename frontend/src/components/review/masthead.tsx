import { ArrowLeftIcon } from "@phosphor-icons/react";
import { cn } from "cn";

/**
 * The one dark surface in the light theme, and the only place the brand shows: a teal-black band with
 * the report's name above the screen's title. Everything below it is paper, hairlines and the three state colours.
 */
export function Masthead({
  title = "Digital Payments: coordinator review",
  wide = false,
  meta,
  onHome,
  kicker = "Cytonn Weekly: all sections",
  children,
}: {
  title?: string;
  /** When set, the kicker becomes the way back to the all-sections overview. */
  onHome?: () => void;
  /** The way back's label, naming the report when it is not the weekly one ("Q3'2026: all sections"). */
  kicker?: string;
  wide?: boolean;
  /** Right-aligned facts about this screen (report week, run number). */
  meta?: React.ReactNode;
  /** One quiet line under the title. */
  children?: React.ReactNode;
}) {
  return (
    <header className="border-b border-band-rule bg-band text-band-foreground">
      <div className={cn("mx-auto w-full px-4 py-6 sm:px-6", wide ? "max-w-375" : "max-w-275")}>
        {onHome ? (
          <button
            type="button"
            onClick={onHome}
            className="eyebrow -mx-1 flex items-center gap-2 rounded-sm px-1 text-band-muted transition-colors outline-none hover:text-band-foreground focus-visible:ring-2 focus-visible:ring-band-muted"
          >
            <ArrowLeftIcon weight="bold" className="size-3" aria-hidden />
            {kicker}
          </button>
        ) : (
          <p className="eyebrow flex items-center gap-2 text-band-muted">
            <span aria-hidden className="block h-0.5 w-4 rounded-full bg-current" />
            Cytonn Weekly
          </p>
        )}
        <div className="mt-2 flex flex-wrap items-end justify-between gap-x-6 gap-y-1">
          <h1 className="text-xl font-semibold sm:text-2xl">{title}</h1>
          {meta && <p className="text-sm text-band-muted">{meta}</p>}
        </div>
        {children && <p className="mt-1 text-sm text-band-muted">{children}</p>}
      </div>
    </header>
  );
}
