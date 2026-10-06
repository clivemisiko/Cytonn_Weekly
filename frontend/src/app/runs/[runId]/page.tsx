import { RunView } from "@/components/run/run-view";

/** One draft run, shown as it happens. The run lives in the API's memory, so the page reads everything from there. */
export default async function RunPage({ params }: PageProps<"/runs/[runId]">) {
  const { runId } = await params;
  return <RunView key={runId} runId={runId} />;
}
