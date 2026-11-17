from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from cytonn_weekly.report_types import WEEKLY, PeriodError, normalize_period
from cytonn_weekly.weekly import export as weekly_export
from api.problems import ProblemError
from api.deps import Deps


def make_router(d: Deps) -> APIRouter:
    router = APIRouter()

    def weekly_period(period: Optional[str]) -> str:
        try:
            return normalize_period(WEEKLY, period)
        except PeriodError as exc:
            raise HTTPException(422, str(exc))


    @router.get("/api/export/weekly")
    def export_weekly_status(period: Optional[str] = Query(default=None, max_length=40)) -> dict:
        """Whether the week's report can be exported: every weekly section's state, and whether it is a dev-mode draft."""
        return weekly_export.export_status(d.db_path, weekly_period(period), inputs_root=d.root)

    @router.get("/api/previous/weekly")
    def previous_weekly() -> dict:
        """Every fully approved weekly week, newest first, the week after the latest of them, and the week the overview opens on."""
        return weekly_export.approved_weeks(d.db_path)

    @router.post("/api/export/weekly")
    def export_weekly(period: Optional[str] = Query(default=None, max_length=40)) -> FileResponse:
        """Write the approved weekly report and return the .docx.  409, naming each section, unless all are approved.

        Nothing is sent or published: the file is handed to the analyst who asked for it.  A dev-mode
        draft is exported with its watermark and banner.
        """
        normalized = weekly_period(period)
        try:
            path = weekly_export.write_weekly_report(d.db_path, normalized, d.export_root, charts_root=d.charts_root,
                                                     inputs_root=d.root)
        except weekly_export.ExportNotAllowed as exc:
            raise ProblemError(409, str(exc), "export_not_ready")
        return FileResponse(path, filename=path.name,
                            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    return router
