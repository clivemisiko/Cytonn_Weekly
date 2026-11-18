from fastapi.routing import APIRoute

from api.main import create_app
from tests.route_helpers import every_route

ROUTES = [
    "DELETE /api/inputs/weekly/{week_ending}/charts/{key}",
    "DELETE /api/inputs/weekly/{week_ending}/{stored_name}",
    "DELETE /api/notable/{section}/decisions/{suggestion_id}",
    "DELETE /api/snips/{week_ending}/{h}",
    "DELETE /api/sources/{source_id}",
    "GET /api/config",
    "GET /api/equities/companies",
    "GET /api/export/weekly",
    "GET /api/health",
    "GET /api/inputs/weekly/{week_ending}",
    "GET /api/inputs/weekly/{week_ending}/analyst",
    "GET /api/inputs/weekly/{week_ending}/charts/{key}/image",
    "GET /api/jobs/{job_id}",
    "GET /api/jobs/{job_id}/messages",
    "GET /api/jobs/{job_id}/readiness",
    "GET /api/notable/{section}",
    "GET /api/previous/weekly",
    "GET /api/report-types",
    "GET /api/reviews/latest",
    "GET /api/reviews/{run_id}",
    "GET /api/reviews/{run_id}/charts/{chart_id}.png",
    "GET /api/reviews/{run_id}/charts/{chart_id}/series",
    "GET /api/reviews/{run_id}/rejected-draft-notes",
    "GET /api/runs/{run_id}",
    "GET /api/runs/{run_id}/events",
    "GET /api/sections",
    "GET /api/snips/{week_ending}",
    "GET /api/snips/{week_ending}/{h}/image",
    "GET /api/sources",
    "GET /api/sources/{source_id}",
    "GET /api/sources/{source_id}/text",
    "PATCH /api/reviews/{run_id}/items/{index}",
    "PATCH /api/snips/{week_ending}/{h}",
    "POST /api/export/weekly",
    "POST /api/export/weekly-rows/{week_ending}",
    "POST /api/inputs/weekly/{week_ending}/analyst/carry",
    "POST /api/inputs/weekly/{week_ending}/analyst/suggest/{field}",
    "POST /api/inputs/weekly/{week_ending}/cbk_bulletin/fetch",
    "POST /api/jobs",
    "POST /api/jobs/{job_id}/messages",
    "POST /api/jobs/{job_id}/raise-budget",
    "POST /api/notable/{section}/decisions",
    "POST /api/reviews/draft",
    "POST /api/reviews/{run_id}/accept-clean",
    "POST /api/reviews/{run_id}/decide",
    "POST /api/reviews/{run_id}/items/{index}/fix-input",
    "POST /api/reviews/{run_id}/items/{index}/remove-finding",
    "POST /api/reviews/{run_id}/items/{index}/sentence",
    "POST /api/runs",
    "POST /api/runs/{run_id}/cancel",
    "POST /api/sections/{slug}/draft",
    "POST /api/snips/{week_ending}/{h}/confirm",
    "POST /api/snips/{week_ending}/{h}/read",
    "POST /api/sources",
    "POST /api/sources/gather",
    "PUT /api/inputs/weekly/{week_ending}/analyst",
    "PUT /api/inputs/weekly/{week_ending}/charts/{key}",
    "PUT /api/inputs/weekly/{week_ending}/charts/{key}/lead-in",
    "PUT /api/inputs/weekly/{week_ending}/charts/{key}/source",
    "PUT /api/inputs/weekly/{week_ending}/notes",
    "PUT /api/inputs/weekly/{week_ending}/{slot}",
    "PUT /api/reviews/{run_id}/charts/{chart_id}/team-chart",
    "PUT /api/snips/{week_ending}/{sector}",
]


def _api_routes(app):
    return [r for r in every_route(app) if isinstance(r, APIRoute) and r.path.startswith("/api/")]


def _app(tmp_path):
    return create_app(db_path=tmp_path / "app.db", load_dotenv=False)


def test_the_api_has_exactly_these_routes_each_once(tmp_path):
    found = sorted(f"{m} {r.path}" for r in _api_routes(_app(tmp_path)) for m in r.methods)
    assert found == sorted(ROUTES)   # a route dropped, added or registered twice fails here, and the list is sorted so the diff reads


def test_where_two_patterns_can_match_one_path_the_specific_one_comes_first(tmp_path):
    order = [f"{m} {r.path}" for r in _api_routes(_app(tmp_path)) for m in r.methods]
    for first, second in [
        ("GET /api/reviews/latest", "GET /api/reviews/{run_id}"),
        ("PUT /api/inputs/weekly/{week_ending}/notes", "PUT /api/inputs/weekly/{week_ending}/{slot}"),
        ("PUT /api/inputs/weekly/{week_ending}/analyst", "PUT /api/inputs/weekly/{week_ending}/{slot}"),
    ]:
        assert order.index(first) < order.index(second), (first, second)
