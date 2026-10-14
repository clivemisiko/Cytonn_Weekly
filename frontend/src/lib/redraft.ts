import type { Decision, ReportType } from "./types";

/**
 * What a coordinator is told before a section that already has a review is drafted again. The API allows it (nothing in
 * the backend refuses a new draft over a decided one); the new run becomes the section's latest, and the weekly export
 * and the Executive Summary read the latest run, so an approval does not carry over to it.
 */
export function redraftNotes(earlier: { run_id: number; decision: Decision | null }, report: ReportType, composesOthers: boolean): string[] {
  const { run_id: run, decision } = earlier;
  const notes = [
    decision === null
      ? `The earlier review (run ${run}) was still in review. It stays saved as it is, undecided, but the overview and this screen offer only the new draft.`
      : `The earlier review (run ${run}, ${decision}) stays saved and read-only.`,
    "The new draft becomes the current one and starts undecided.",
  ];
  if (decision === "approved" && !composesOthers) {
    notes.push(
      report === "weekly"
        ? "This section is approved now. The weekly export needs it approved again."
        : "This section is approved now. The Executive Summary needs it approved again, and one already composed keeps the text it was made from.",
    );
  }
  return notes;
}
