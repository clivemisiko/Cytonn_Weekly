"use client";

import { cn } from "cn";
import { useReviewSession } from "@/hooks/use-review-session";
import { weekRange } from "@/lib/format";
import { isBlocksSection, type Review } from "@/lib/types";
import { DevRibbon, LockBar } from "./banners";
import { BlocksPane } from "./blocks-pane";
import { DraftPane } from "./draft-pane";
import { ItemsPane } from "./items-pane";
import { Masthead } from "./masthead";
import { Scorecard } from "./scorecard";
import { StatusBar } from "./status-bar";

/**
 * One open review: the sticky status bar (progress and the decision), the scorecard, and the drafted section beside its review items.
 * The tool never approves anything; this screen only records what the coordinator decides.
 */
export function ReviewScreen({ initial, onClose }: { initial: Review; onClose: () => void }) {
  const session = useReviewSession(initial);
  const { review } = session;
  const dev = review.is_dev_draft && review.dev_mode_label;

  return (
    <>
      {dev && <DevRibbon label={review.dev_mode_label!} />}
      <div className={cn(dev && "pt-7")}>
        <Masthead
          wide
          title={`${review.section_title}: coordinator review`}
          onHome={onClose}
          kicker={review.period ? `${review.period}: all sections` : undefined}
          meta={
            review.period && review.report_type !== "weekly" ? (
              <>
                {review.report_title}, <span className="font-mono">{review.period}</span>, run{" "}
                <span className="font-mono">{review.run_id}</span>
              </>
            ) : (
              <>
                {review.period ? <span className="font-mono">{review.period}</span> : "Report week"}{" "}
                {weekRange(review.section.week_start, review.section.week_end)}, run{" "}
                <span className="font-mono">{review.run_id}</span>
              </>
            )
          }
        />
        <div className="mx-auto w-full max-w-375 px-4 pb-16 sm:px-6">
          <StatusBar
            review={review}
            saving={session.saving}
            saveError={session.saveError}
            hasDevRibbon={Boolean(dev)}
            deciding={session.deciding}
            decisionError={session.decisionError}
            onDecide={session.decide}
            onClose={onClose}
          />

          <div className="space-y-6 pt-6">
            {review.decision && <LockBar decision={review.decision} decidedAt={review.decided_at} />}
            <Scorecard review={review} />
            <div className="grid grid-cols-1 items-start gap-x-8 gap-y-8 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
              {isBlocksSection(review.section) ? (
                <BlocksPane review={review} section={review.section} />
              ) : (
                <DraftPane review={review} section={review.section} />
              )}
              <ItemsPane
                review={review}
                locked={review.locked}
                onResolve={session.resolve}
                onAcceptClean={session.acceptClean}
              />
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
