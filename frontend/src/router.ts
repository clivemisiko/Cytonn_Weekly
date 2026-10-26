import { createRouter, createWebHistory } from "vue-router";

// The query parameters the overview used when it lived at "/". A request that carries any of them is an old bookmark
// of a report, so it goes to the overview with its whole query string intact.
const OVERVIEW_PARAMS = ["report", "period", "kind"];

/** The three addresses: the landing page, the overview (whose screens are phases), one draft run. */
export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      component: () => import("./pages/LandingPage.vue"),
      beforeEnter: (to) => (OVERVIEW_PARAMS.some((name) => to.query[name] !== undefined) ? { path: "/overview", query: to.query, replace: true } : true),
    },
    { path: "/overview", component: () => import("./pages/OverviewPage.vue") },
    {
      path: "/sections/:slug",
      redirect: (to) => ({ path: "/overview", query: { ...to.query, section: to.params.slug } }),
    },
    {
      path: "/reviews/:reviewId",
      redirect: (to) => ({ path: "/overview", query: { ...to.query, review: to.params.reviewId } }),
    },
    { path: "/runs/:runId", component: () => import("./pages/RunPage.vue"), props: true },
    { path: "/:rest(.*)*", component: () => import("./pages/NotFoundPage.vue") },
  ],
});
