from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from cytonn_weekly.weekly import analyst as weekly_analyst
from cytonn_weekly.weekly import chart_uploads
from cytonn_weekly.weekly import inputs as weekly_inputs
from api.problems import ProblemError
from api.deps import Deps, failure_message, week_of
from api.schemas import InputNotes, ChartLeadIn, ChartSource, AnalystInputs


def make_router(d: Deps) -> APIRouter:
    router = APIRouter()

    def slot_of(slug: str) -> weekly_inputs.Slot:
        slot = weekly_inputs.BY_SLUG.get(slug)
        if slot is None:
            raise HTTPException(404, f"no weekly input {slug!r}")
        return slot


    @router.get("/api/inputs/weekly/{week_ending}")
    def inputs_status(week_ending: str) -> dict:
        """What has been received for the week ending ``week_ending``: per input, the date read from it and whether it fits."""
        return weekly_inputs.status(week_of(week_ending), d.root)

    @router.put("/api/inputs/weekly/{week_ending}/notes")
    def put_input_notes(week_ending: str, body: InputNotes) -> dict:
        week = week_of(week_ending)
        try:
            weekly_inputs.write_notes(week, {k: getattr(body, k) for k in body.model_fields_set}, d.root)
        except weekly_inputs.InputError as exc:
            raise ProblemError(422, str(exc), "note_refused")
        return weekly_inputs.status(week, d.root)

    def form_section(section: Optional[str]) -> Optional[str]:
        if section is not None and section not in weekly_analyst.WORKBOOKS:
            raise HTTPException(422, f"no weekly analyst inputs for section {section!r}")
        return section

    @router.get("/api/inputs/weekly/{week_ending}/analyst")
    def analyst_inputs(week_ending: str, section: Optional[str] = Query(default=None, max_length=40)) -> dict:
        """The weekly analyst inputs form: each item with what was typed, what an uploaded workbook holds, and where they differ."""
        return weekly_analyst.status(week_of(week_ending), d.root, form_section(section))

    @router.put("/api/inputs/weekly/{week_ending}/analyst")
    def put_analyst_inputs(week_ending: str, body: AnalystInputs,
                           section: Optional[str] = Query(default=None, max_length=40)) -> dict:
        """Keep what was typed.  422, with every reason (one a line), if any value is refused; nothing is stored then."""
        week, section = week_of(week_ending), form_section(section)
        try:
            weekly_analyst.save_form(week, {"fields": body.fields, "tables": body.tables, "confirm": body.confirm}, d.root)
        except weekly_inputs.InputError as exc:
            raise ProblemError(422, str(exc), "analyst_refused")
        return weekly_analyst.status(week, d.root, section)

    @router.post("/api/inputs/weekly/{week_ending}/analyst/carry")
    def carry_analyst_inputs(week_ending: str, section: Optional[str] = Query(default=None, max_length=40)) -> dict:
        """Start this week's form from last week's.  409, with the reason, if there is nothing to carry.

        Every carried value is marked with the week it came from; a weekly-changing one is read by
        no draft until it is confirmed (PUT .../analyst with ``confirm``).
        """
        week, section = week_of(week_ending), form_section(section)
        try:
            weekly_analyst.carry_forward(week, d.root)
        except weekly_inputs.InputError as exc:
            raise ProblemError(409, str(exc), "analyst_nothing_to_carry")
        return weekly_analyst.status(week, d.root, section)

    @router.post("/api/inputs/weekly/{week_ending}/analyst/suggest/{field}")
    def suggest_analyst_input(week_ending: str, field: str, section: Optional[str] = Query(default=None, max_length=40)) -> dict:
        """Work out a suggestion for a running total and keep it, unconfirmed, with its working.  409 if none can be."""
        week, section = week_of(week_ending), form_section(section)
        if field not in weekly_analyst.SUGGESTED_FIELDS:
            raise HTTPException(404, f"no suggestion is worked out for {field!r}")
        from cytonn_weekly.equities.weekly import running_total_suggestions   # imported here: it pulls in the OCR reader

        found = running_total_suggestions(weekly_inputs.WeeklyInputs(week, d.root), d.fetch_usd_rates)[field]
        if "reason" in found:
            raise ProblemError(409, found["reason"], "analyst_suggestion_unavailable")
        try:
            weekly_analyst.suggest(week, field, found["value"], found["note"], d.root)
        except weekly_inputs.InputError as exc:
            raise ProblemError(409, str(exc), "analyst_suggestion_unavailable")
        return weekly_analyst.status(week, d.root, section)

    def chart_key(key: str) -> str:
        if key not in chart_uploads.KEYS:
            raise HTTPException(404, f"no chart slot {key!r}")
        return key

    @router.put("/api/inputs/weekly/{week_ending}/charts/{key}")
    async def upload_chart(week_ending: str, key: str, request: Request) -> dict:
        """Upload one chart image (PNG or JPEG, judged by its first bytes): the file is the request body.

        It replaces the slot's earlier image. 413 over the size limit, 422 when it is empty or not an image.
        The image is kept for the Word export only; no draft reads it.
        """
        week, key = week_of(week_ending), chart_key(key)
        too_big = (f"The image is over the {chart_uploads.MAX_BYTES // 1_048_576} MB limit. "
                   "Save a smaller copy and upload that.")
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > chart_uploads.MAX_BYTES:
            raise ProblemError(413, too_big, "upload_too_big")
        data = await request.body()
        if len(data) > chart_uploads.MAX_BYTES:
            raise ProblemError(413, too_big, "upload_too_big")
        try:
            await run_in_threadpool(chart_uploads.store, week, key, data, d.root)
        except weekly_inputs.InputError as exc:
            raise ProblemError(422, str(exc), "upload_refused")
        return weekly_inputs.status(week, d.root)

    @router.get("/api/inputs/weekly/{week_ending}/charts/{key}/image")
    def chart_upload_image(week_ending: str, key: str) -> Response:
        week, key = week_of(week_ending), chart_key(key)
        stored = chart_uploads.image(week, key, d.root)
        if stored is None:
            raise HTTPException(404, "this chart has no image")
        return Response(stored[0], media_type=chart_uploads.MEDIA_TYPE[stored[1]], headers={"Cache-Control": "no-store"})

    @router.delete("/api/inputs/weekly/{week_ending}/charts/{key}")
    def delete_chart(week_ending: str, key: str) -> dict:
        week, key = week_of(week_ending), chart_key(key)
        if not chart_uploads.remove(week, key, d.root):
            raise HTTPException(404, "this chart has no image")
        return weekly_inputs.status(week, d.root)

    @router.put("/api/inputs/weekly/{week_ending}/charts/{key}/lead-in")
    def put_chart_lead_in(week_ending: str, key: str, body: ChartLeadIn) -> dict:
        week, key = week_of(week_ending), chart_key(key)
        try:
            chart_uploads.set_lead_in(week, key, body.lead_in, d.root)
        except weekly_inputs.InputError as exc:
            raise ProblemError(422, str(exc), "note_refused")
        return weekly_inputs.status(week, d.root)

    @router.put("/api/inputs/weekly/{week_ending}/charts/{key}/source")
    def put_chart_source(week_ending: str, key: str, body: ChartSource) -> dict:
        week, key = week_of(week_ending), chart_key(key)
        try:
            chart_uploads.set_source(week, key, body.source, d.root)
        except weekly_inputs.InputError as exc:
            raise ProblemError(422, str(exc), "note_refused")
        return weekly_inputs.status(week, d.root)

    @router.put("/api/inputs/weekly/{week_ending}/{slot}")
    async def upload_input(week_ending: str, slot: str, request: Request,
                           filename: str = Query(default="", max_length=260)) -> dict:
        """Upload one input: the file is the request body.  It is checked and read before it is kept.

        413 if it is over the size limit, 422 (with the reason) if it is not the document the
        slot takes, or is a KCB daily report for a day outside the week.
        """
        week, spec = week_of(week_ending), slot_of(slot)
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > weekly_inputs.MAX_BYTES:
            raise ProblemError(413, f"{spec.title}: the file is over the {weekly_inputs.MAX_BYTES // 1_048_576} MB limit. "
                                     "Upload a smaller copy of the file.", "upload_too_big")
        data = await request.body()
        if len(data) > weekly_inputs.MAX_BYTES:
            raise ProblemError(413, f"{spec.title}: the file is over the {weekly_inputs.MAX_BYTES // 1_048_576} MB limit. "
                                     "Upload a smaller copy of the file.", "upload_too_big")
        try:
            await run_in_threadpool(weekly_inputs.store, week, slot, data, filename, d.root)
        except weekly_inputs.InputError as exc:
            raise ProblemError(422, str(exc), "upload_refused")
        return weekly_inputs.status(week, d.root)

    @router.post("/api/inputs/weekly/{week_ending}/cbk_bulletin/fetch")
    def fetch_bulletin_input(week_ending: str) -> dict:
        """Fetch the week's CBK Weekly Bulletin from centralbank.go.ke and keep it as an input."""
        week = week_of(week_ending)
        try:
            data, url = d.fetch_bulletin(week.ending)
        except LookupError as exc:
            raise ProblemError(404, f"{exc}. CBK may not have published it yet: try again later, or upload the PDF yourself.", "bulletin_not_published")
        except Exception as exc:  # noqa: BLE001 - shown to the analyst, not swallowed
            raise ProblemError(502, f"The bulletin could not be fetched from CBK. {failure_message(exc)} You can also upload "
                                     "the PDF yourself.", "bulletin_fetch_failed")
        try:
            weekly_inputs.store(week, weekly_inputs.CBK_BULLETIN, data, url.rsplit("/", 1)[-1], d.root, fetched_from=url)
        except weekly_inputs.InputError as exc:
            raise ProblemError(502, f"CBK's file was downloaded but could not be read as the Weekly Bulletin ({exc}). Upload "
                                     "the bulletin yourself.", "bulletin_fetch_failed")
        return weekly_inputs.status(week, d.root)


    @router.delete("/api/inputs/weekly/{week_ending}/{stored_name}")
    def delete_input(week_ending: str, stored_name: str) -> dict:
        week = week_of(week_ending)
        if not weekly_inputs.remove(week, stored_name, d.root):
            raise HTTPException(404, f"no stored input {stored_name!r} for the week ending {week.ending.isoformat()}")
        return weekly_inputs.status(week, d.root)

    return router
