import { redirect } from "next/navigation";
import { LandingPage } from "@/components/landing/landing-page";

// The query parameters the overview used when it lived at "/" (review-app.tsx). A request that carries any of them is
// an old bookmark of a report, so it goes to the overview with its whole query string intact.
const OVERVIEW_PARAMS = ["report", "period", "kind"];

export default async function Home({ searchParams }: PageProps<"/">) {
  const params = await searchParams;
  if (OVERVIEW_PARAMS.some((name) => params[name] !== undefined)) {
    const query = new URLSearchParams();
    for (const [name, value] of Object.entries(params)) {
      for (const v of Array.isArray(value) ? value : [value]) {
        if (v !== undefined) query.append(name, v);
      }
    }
    redirect(`/overview?${query.toString()}`);
  }
  return <LandingPage />;
}
