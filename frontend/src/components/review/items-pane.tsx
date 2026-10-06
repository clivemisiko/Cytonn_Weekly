"use client";

import { useState } from "react";
import { AnimatePresence, LayoutGroup, motion } from "motion/react";
import { CaretDownIcon } from "@phosphor-icons/react";
import { cn } from "cn";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { STATUS_META, STATUS_ORDER } from "@/lib/format";
import type { Resolution, Review, Status } from "@/lib/types";
import { ReviewItemCard } from "./review-item-card";

const EASE = [0.23, 1, 0.32, 1] as const;

function Group({
  status,
  review,
  locked,
  defaultOpen,
  onResolve,
  onAcceptClean,
}: {
  status: Status;
  review: Review;
  locked: boolean;
  defaultOpen: boolean;
  onResolve: (index: number, resolution: Resolution, note?: string) => Promise<boolean>;
  onAcceptClean: () => Promise<boolean>;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const meta = STATUS_META[status];
  const items = review.review_items.filter((i) => i.status === status);
  const unresolved = review.counts[status].unresolved;
  const panelId = `group-${status}`;

  return (
    <section className={cn(`state-${status}`)} aria-labelledby={`${panelId}-title`}>
      <Collapsible open={open} onOpenChange={setOpen}>
        <h3 id={`${panelId}-title`} className="text-base font-semibold">
          <CollapsibleTrigger className="state-rule flex w-full items-center gap-2 border-b py-2 text-left transition-colors outline-none hover:bg-muted/60 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset">
            <span className="glyph size-4 text-xs" aria-hidden>
              {meta.glyph}
            </span>
            <span>
              {meta.title} <span className="font-mono text-sm font-medium text-muted-foreground">({items.length})</span>
            </span>
            <CaretDownIcon
              weight="bold"
              aria-hidden
              className={cn("ml-auto size-4 text-muted-foreground transition-transform duration-200 ease-out", open && "rotate-180")}
            />
          </CollapsibleTrigger>
        </h3>

        {status === "clean" && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 pt-3">
            <p className="text-xs text-muted-foreground">Checked with no flag. Listed so you can see full coverage.</p>
            <Button
              size="sm"
              disabled={locked || unresolved === 0}
              onClick={() => void onAcceptClean()}
            >
              Mark all clean as accepted ({unresolved} unresolved)
            </Button>
          </div>
        )}

        <AnimatePresence initial={false}>
          {open && (
            <CollapsibleContent forceMount asChild>
              <motion.div
                id={panelId}
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.2, ease: EASE }}
                className="-m-1 overflow-hidden p-1"
              >
                {items.length === 0 ? (
                  <p className="pt-3 text-sm text-muted-foreground">None.</p>
                ) : (
                  <ul className="space-y-3 pt-3">
                    {items.map((item) => (
                      <ReviewItemCard key={item.index} item={item} locked={locked} onResolve={onResolve} />
                    ))}
                  </ul>
                )}
              </motion.div>
            </CollapsibleContent>
          )}
        </AnimatePresence>
      </Collapsible>
    </section>
  );
}

/** Review items grouped Flagged, Not auto-verified, Clean. Clean starts collapsed: it is coverage, not work. */
export function ItemsPane({
  review,
  locked,
  onResolve,
  onAcceptClean,
}: {
  review: Review;
  locked: boolean;
  onResolve: (index: number, resolution: Resolution, note?: string) => Promise<boolean>;
  onAcceptClean: () => Promise<boolean>;
}) {
  return (
    <section aria-labelledby="items-title" className="min-w-0 space-y-6 [overflow-wrap:anywhere]">
      <h2 id="items-title" className="text-lg font-semibold">
        Review items
      </h2>
      <LayoutGroup id="items">
        {STATUS_ORDER.map((status) => (
          <Group
            key={status}
            status={status}
            review={review}
            locked={locked}
            defaultOpen={status !== "clean"}
            onResolve={onResolve}
            onAcceptClean={onAcceptClean}
          />
        ))}
      </LayoutGroup>
    </section>
  );
}
