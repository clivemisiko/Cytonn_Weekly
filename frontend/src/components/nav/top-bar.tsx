import { ThemeToggle } from "./theme-toggle";

/**
 * The one bar at the top of every page, always in view while the page scrolls. It is the band's colour, so it reads
 * as the top edge of the masthead under it, and it is 44px tall (--topbar-h in globals.css), which everything that
 * sticks below it offsets by.
 */
export function TopBar() {
  return (
    <header className="sticky top-0 z-40 h-(--topbar-h) border-b border-band-rule bg-band text-band-foreground">
      <nav aria-label="App" className="mx-auto flex h-full w-full max-w-375 items-center justify-end gap-2 px-2 sm:px-4">
        <ThemeToggle />
      </nav>
    </header>
  );
}
