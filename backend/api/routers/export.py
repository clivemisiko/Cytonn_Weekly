from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from cytonn_weekly.report_types import WEEKLY, PeriodError, normalize_period
from cytonn_weekly.history import rows_export
from cytonn_weekly.weekly import export as weekly_export
from cytonn_weekly.weekly import inputs as weekly_inputs
from cytonn_weekly.weekly.workbook import WorkbookError
from api.problems import ProblemError
from api.deps import Deps, week_of
from api.runs import ACTIVE, FAILED


def make_router(d: Deps) -> APIRouter:
    router = APIRouter()

    def weekly_period(period: Optional[str]) -> str:
        try:
            return normalize_period(WEEKLY, period)
        except PeriodError as exc:
            raise HTTPException(422, str(exc))


    def live(period: str) -> dict[str, str]:
        """Each weekly section of this period whose newest run is still going ("drafting") or failed ("failed")."""
        return {r.section: "drafting" if r.status in ACTIVE else "failed" for r in d.runs.latest_by_key()
                if r.key[:2] == (WEEKLY, period) and (r.status in ACTIVE or r.status == FAILED)}

    def docx(path) -> FileResponse:
        return FileResponse(path, filename=path.name,
                            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    @router.get("/api/export/weekly")
    def export_weekly_status(period: Optional[str] = Query(default=None, max_length=40)) -> dict:
        """What the export holds: every weekly section's state, what is left out and why, and whether it is a dev-mode draft."""
        normalized = weekly_period(period)
        return weekly_export.export_status(d.db_path, normalized, inputs_root=d.root, live=live(normalized))

    @router.get("/api/previous/weekly")
    def previous_weekly() -> dict:
        """Every fully approved weekly week, newest first, the week after the latest of them, and the week the overview opens on."""
        return weekly_export.approved_weeks(d.db_path)

    @router.post("/api/export/weekly")
    def export_weekly(period: Optional[str] = Query(default=None, max_length=40)) -> FileResponse:
        """Write every section whose draft is finished, approved or not, and return the .docx.  409 when none is.

        Nothing is sent or published: the file is handed to the analyst who asked for it.  A dev-mode
        draft is exported with its watermark and banner.
        """
        return docx(write(weekly_period(period), None))

    @router.post("/api/export/weekly/{section}")
    def export_weekly_section(section: str, period: Optional[str] = Query(default=None, max_length=40)) -> FileResponse:
        """One section's finished draft as its own .docx, with the full export's renderer.  409 until its draft is finished."""
        return docx(write(weekly_period(period), section))

    def write(normalized: str, section: Optional[str]):
        try:
            return weekly_export.write_weekly_report(d.db_path, normalized, d.export_root, charts_root=d.charts_root,
                                                     inputs_root=d.root, live=live(normalized), section=section)
        except weekly_export.ExportNotAllowed as exc:
            raise ProblemError(409, str(exc), "export_not_ready")

    @router.post("/api/export/weekly-rows/{week_ending}")
    def export_weekly_rows(week_ending: str) -> FileResponse:
        """Write this week's rows from the history store as a small .xlsx for the analyst to paste into the master workbooks, and return it.

        Only confirmed points; a missing one is an empty cell with a note.  The uploaded workbooks are read, never changed.
        """
        week = week_of(week_ending)
        inputs = weekly_inputs.WeeklyInputs(week, d.root)
        try:
            equities, fixed_income = inputs.equities_book, inputs.fi_book
        except WorkbookError as exc:
            raise HTTPException(409, f"An uploaded workbook cannot be read, so the layout cannot be taken from it: {exc}")
        path = rows_export.write(week, d.db_path, d.export_root, equities, fixed_income)
        return FileResponse(path, filename=path.name, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    return router
