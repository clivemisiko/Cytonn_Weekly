import { createRouter, createWebHistory } from "vue-router";
import { chooserHref } from "./lib/nav";

// The query parameters the overview used when it lived at "/". A request that carries any of them is an old bookmark
// of a report, so it goes to /overview with its whole query string intact.
const OVERVIEW_PARAMS = ["report", "period", "kind"];
const one = (v: unknown) => (Array.isArray(v) ? String(v[0] ?? "") : typeof v === "string" ? v : "");

/** The addresses: the landing page, the overview (whose screens are phases), the chat, one draft run. */
export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      component: () => import("./pages/LandingPage.vue"),
      beforeEnter: (to) => (OVERVIEW_PARAMS.some((name) => to.query[name] !== undefined) ? { path: "/overview", query: to.query, replace: true } : true),
    },
    // A section's start screen (?section=) and a saved review (?review=) keep this address; the overview itself is gone, so
    // an old bookmark of it opens the section chooser for the same week.
    {
      path: "/overview",
      component: () => import("./pages/OverviewPage.vue"),
      beforeEnter: (to) =>
        one(to.query.review) || one(to.query.section)
          ? true
          : chooserHref({ type: one(to.query.report) || "weekly", period: one(to.query.period), kind: one(to.query.kind) }),
    },
    { path: "/previous", component: () => import("./pages/PreviousReportsPage.vue") },
    { path: "/chat", component: () => import("./pages/ChatPage.vue") },
    {
      path: "/sections/:slug",
      redirect: (to) => ({ path: "/overview", query: { ...to.query, section: to.params.slug } }),
    },
    {
      path: "/reviews/:reviewId",
      redirect: (to) => ({ path: "/overview", query: { ...to.query, review: to.params.reviewId } }),
    },
    { path: "/runs/:runId", component: () => import("./pages/RunPage.vue"), props: true },
    { path: "/sources/:sourceId", component: () => import("./pages/SourcePage.vue"), props: true },
    { path: "/:rest(.*)*", component: () => import("./pages/NotFoundPage.vue") },
  ],
});
