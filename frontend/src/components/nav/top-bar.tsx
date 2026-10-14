"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ArrowLeftIcon, HouseIcon } from "@phosphor-icons/react";
import { HOME, mayLeave, useBackTarget } from "@/lib/nav";
import { ThemeToggle } from "./theme-toggle";

// One look for Home and Back: 40px tall (the touch target), text and icon in the band's ink, a visible focus ring.
const CONTROL =
  "inline-flex h-10 items-center gap-2 rounded-md px-3 text-sm font-semibold text-band-foreground outline-none transition-colors duration-150 hover:bg-band-foreground/10 focus-visible:ring-2 focus-visible:ring-band-muted focus-visible:ring-inset disabled:cursor-not-allowed disabled:text-band-muted/60 disabled:hover:bg-transparent aria-[current=page]:text-band-muted";

/**
 * The one bar at the top of every page, always in view while the page scrolls: Home, Back and the theme. It is the
 * band's colour, so it reads as the top edge of the masthead under it, and it is 44px tall (--topbar-h in
 * globals.css), which everything that sticks below it offsets by.
 *
 * Home always goes to the start screen. Back goes where the page on screen says (lib/nav.ts): its own parent, or
 * Home when it has none; on the start screen it is disabled, not hidden. Neither ever leaves the app. Both ask first
 * when the page holds unsaved edits.
 */
export function TopBar() {
  const router = useRouter();
  const pathname = usePathname();
  const back = useBackTarget();
  const atHome = pathname === HOME;

  const goBack = () => {
    if (!mayLeave()) return;
    if (back.kind === "go") back.go();
    else router.push(back.kind === "href" ? back.href : HOME);
  };
  const backTo = back.kind === "go" || back.kind === "href" ? back.to : "Home";

  return (
    <header className="sticky top-0 z-40 h-(--topbar-h) border-b border-band-rule bg-band text-band-foreground">
      <nav aria-label="App" className="mx-auto flex h-full w-full max-w-375 items-center gap-1 px-2 sm:px-4">
        <Link
          href={HOME}
          aria-label="Home"
          aria-current={atHome ? "page" : undefined}
          className={CONTROL}
          onClick={(event) => {
            if (!mayLeave()) event.preventDefault();
          }}
        >
          <HouseIcon weight="bold" className="size-4" aria-hidden />
          Home
        </Link>
        <button
          type="button"
          className={CONTROL}
          disabled={back.kind === "none"}
          aria-label={back.kind === "none" ? "Back (this is the start screen)" : `Back to ${backTo}`}
          title={back.kind === "none" ? "This is the start screen" : `Back to ${backTo}`}
          onClick={goBack}
        >
          <ArrowLeftIcon weight="bold" className="size-4" aria-hidden />
          Back
        </button>
        <div className="ml-auto">
          <ThemeToggle />
        </div>
      </nav>
    </header>
  );
}
