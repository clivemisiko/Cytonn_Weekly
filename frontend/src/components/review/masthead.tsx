import { cn } from "cn";

/**
 * The one dark surface in the light theme, and the only place the brand shows: a teal-black band with
 * the report's name above the screen's title. Everything below it is paper, hairlines and the three state colours.
 * The way back is not here: Home and Back are on the top bar (components/nav/top-bar.tsx), which never scrolls away.
 */
export function Masthead({
  title = "Digital Payments: coordinator review",
  wide = false,
  meta,
  children,
}: {
  title?: string;
  wide?: boolean;
  /** Right-aligned facts about this screen (report week, run number). */
  meta?: React.ReactNode;
  /** One quiet line under the title. */
  children?: React.ReactNode;
}) {
  return (
    <header className="border-b border-band-rule bg-band text-band-foreground">
      <div className={cn("mx-auto w-full px-4 py-6 sm:px-6", wide ? "max-w-375" : "max-w-275")}>
        <p className="eyebrow flex items-center gap-2 text-band-muted">
          <span aria-hidden className="block h-0.5 w-4 rounded-full bg-current" />
          Cytonn Weekly
        </p>
        <div className="mt-2 flex flex-wrap items-end justify-between gap-x-6 gap-y-1">
          <h1 className="text-xl font-semibold sm:text-2xl">{title}</h1>
          {meta && <p className="text-sm text-band-muted">{meta}</p>}
        </div>
        {children && <p className="mt-1 text-sm text-band-muted">{children}</p>}
      </div>
    </header>
  );
}
