"use client";

import { useSyncExternalStore } from "react";
import { RadioGroup as RadioGroupPrimitive } from "radix-ui";
import { MonitorIcon, MoonIcon, SunIcon } from "@phosphor-icons/react";
import { cn } from "cn";
import { THEMES, type ThemeChoice, currentTheme, setTheme, subscribeTheme } from "@/lib/theme";

const OPTIONS: Record<ThemeChoice, { label: string; Icon: typeof SunIcon }> = {
  light: { label: "Light", Icon: SunIcon },
  dark: { label: "Dark", Icon: MoonIcon },
  system: { label: "System", Icon: MonitorIcon },
};

// The server cannot know the stored choice; it renders System, and the page's own attribute takes over once live.
const serverTheme = (): ThemeChoice => "system";

/**
 * Light | Dark | System, as one radio group on the top bar (arrow keys move between them, one tab stop). The current
 * choice is shown three ways, never by colour alone: the filled icon in a framed box, the word beside the group from
 * the sm breakpoint up, and the group's own name ("Theme: Dark").
 */
export function ThemeToggle() {
  const choice = useSyncExternalStore(subscribeTheme, currentTheme, serverTheme);
  return (
    <div className="flex items-center gap-2">
      <span className="hidden text-xs text-band-muted sm:inline" aria-hidden>
        Theme: <span className="font-semibold text-band-foreground">{OPTIONS[choice].label}</span>
      </span>
      <RadioGroupPrimitive.Root
        value={choice}
        onValueChange={(next) => setTheme(next as ThemeChoice)}
        orientation="horizontal"
        aria-label={`Theme: ${OPTIONS[choice].label}`}
        className="flex items-center"
      >
        {THEMES.map((theme) => {
          const { label, Icon } = OPTIONS[theme];
          const selected = theme === choice;
          return (
            <RadioGroupPrimitive.Item
              key={theme}
              value={theme}
              aria-label={`${label} theme`}
              title={`${label} theme`}
              className="group grid size-10 place-items-center rounded-md outline-none focus-visible:ring-2 focus-visible:ring-band-muted focus-visible:ring-inset"
            >
              <span
                className={cn(
                  "grid size-8 place-items-center rounded-md border transition-colors duration-150",
                  selected
                    ? "border-band-muted bg-band-foreground/15 text-band-foreground"
                    : "border-transparent text-band-muted group-hover:bg-band-foreground/10 group-hover:text-band-foreground",
                )}
              >
                <Icon weight={selected ? "fill" : "regular"} className="size-4" aria-hidden />
              </span>
            </RadioGroupPrimitive.Item>
          );
        })}
      </RadioGroupPrimitive.Root>
    </div>
  );
}
