from datetime import date
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from cytonn_weekly.common import sources as source_store
from cytonn_weekly.digital_payments.provider_factory import NOT_CONFIGURED
from cytonn_weekly.narrative import bedrock_provider
from cytonn_weekly.narrative.base import SnipReadError
from cytonn_weekly.narrative.factory import get_narrative_provider
from cytonn_weekly.real_estate import snips as snip_store
from cytonn_weekly.report_types import WEEKLY
from cytonn_weekly.weekly.week import latest_friday
from api.draft_slot import DraftBusy, busy_message
from api.deps import Deps, configured_provider, week_of
from api.schemas import SnipChange


def make_router(d: Deps) -> APIRouter:
    router = APIRouter()

    def snip_day(week_ending: str) -> date:
        return date.fromisoformat(week_of(week_ending).ending.isoformat())

    def snip_view(day: date) -> dict:
        try:
            items = snip_store.list_snips(day, d.snips_dir)
            warnings = snip_store.misfiled_lines(day, d.snips_dir, d.sources_dir)
        except snip_store.SnipError as exc:
            raise HTTPException(409, str(exc))
        return {"week_ending": day.isoformat(), "sectors": [{"id": i, "label": label} for i, label in snip_store.SECTORS],
                "max_per_sector": snip_store.MAX_PER_SECTOR, "max_bytes": snip_store.MAX_BYTES,
                "pdf_max_bytes": snip_store.PDF_MAX_BYTES, "pdf_max_pages": snip_store.PDF_MAX_PAGES, "snips": items,
                "warnings": warnings}

    def snip_guard(day: date, h: str, *also: str) -> None:
        """A confirmed snip is a source of its sector's piece, so none may change while a draft reads that piece."""
        entry = next((e for e in snip_store.list_snips(day, d.snips_dir) if e["hash"] == h), None)
        labels = {snip_store.LABELS[s] for s in (entry["sector"] if entry else None, *also) if s in snip_store.LABELS}
        for label in labels:
            d.refuse_while_drafting(label, latest_friday(day).isoformat())

    @router.get("/api/snips/{week_ending}")
    def list_snips(week_ending: str) -> dict:
        return snip_view(snip_day(week_ending))

    @router.put("/api/snips/{week_ending}/{sector}")
    async def upload_snip(week_ending: str, sector: str, request: Request, filename: str = Query(default="", max_length=200)) -> dict:
        """Upload one image (PNG, JPEG or WebP) or PDF, judged by its first bytes, for one sector: the file is the request
        body. Nothing is read from it here and nothing is fetched. The image limit is checked in snip_store.add."""
        day = snip_day(week_ending)
        declared = request.headers.get("content-length")
        too_big = HTTPException(413, f"The file is over the {snip_store.PDF_MAX_BYTES // 1_048_576} MB limit for a PDF "
                                     f"({snip_store.MAX_BYTES // 1_048_576} MB for an image).")
        if declared and declared.isdigit() and int(declared) > snip_store.PDF_MAX_BYTES:
            raise too_big
        data = await request.body()
        if len(data) > snip_store.PDF_MAX_BYTES:
            raise too_big
        try:
            await run_in_threadpool(snip_store.add, day, sector, filename, data, d.snips_dir)
        except snip_store.SnipError as exc:
            raise HTTPException(422, str(exc))
        return snip_view(day)

    @router.get("/api/snips/{week_ending}/{h}/image")
    def snip_image(week_ending: str, h: str) -> Response:
        try:
            data, media = snip_store.image_bytes(snip_day(week_ending), h, d.snips_dir)
        except (snip_store.SnipError, OSError) as exc:
            raise HTTPException(404, str(exc))
        headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
        if media == "application/pdf":   # downloaded, never opened in the page, so nothing in it runs here
            headers["Content-Disposition"] = "attachment"
        return Response(data, media_type=media, headers=headers)

    @router.post("/api/snips/{week_ending}/{h}/read")
    def read_snip(week_ending: str, h: str) -> dict:
        """One vision call for this snip, unless it has been read before (the reading is kept by the image's hash). It takes
        a drafting seat like a draft does, so reads and drafts share the same limit."""
        day = snip_day(week_ending)
        try:
            entry = next((e for e in snip_store.list_snips(day, d.snips_dir) if e["hash"] == h), None)
            if entry is None:
                raise HTTPException(404, "That snip is not in this week's list. Reload the page.")
            if entry["text"] is not None:
                return snip_view(day)
            if not configured_provider():
                raise HTTPException(409, NOT_CONFIGURED)
            if configured_provider() == "bedrock":
                problem = bedrock_provider.env_problem()
                if problem:
                    raise HTTPException(409, problem)
            provider = get_narrative_provider()
            try:
                claim, _ = d.draft_slot.claim("real_estate", "Real Estate (reading snips)", WEEKLY, "")
            except DraftBusy as exc:
                raise HTTPException(409, busy_message(exc))
            try:
                if entry.get("kind") == "pdf":   # each chunk of page text, then every quote checked against its page
                    pages, ocr_pages = snip_store.pdf_pages(day, h, d.snips_dir)
                    found = [p for chunk in snip_store.pdf_chunks(pages)
                             for p in provider.read_pdf_passages(snip_store.LABELS[entry["sector"]], chunk)]
                    passages, dropped = snip_store.check_passages(found, pages)
                else:
                    data, media = snip_store.image_bytes(day, h, d.snips_dir)
                    text = provider.read_snip(data, media)
            except SnipReadError as exc:
                raise HTTPException(409, str(exc))
            except bedrock_provider.BedrockError as exc:
                raise HTTPException(502, str(exc))
            finally:
                d.free_seat(claim)
            if entry.get("kind") == "pdf":
                snip_store.pdf_reading(day, h, {"passages": passages, "dropped": dropped, "ocr_pages": ocr_pages}, d.snips_dir)
            else:
                snip_store.reading(day, h, text, d.snips_dir)
        except snip_store.SnipError as exc:
            raise HTTPException(422, str(exc))
        return snip_view(day)

    @router.patch("/api/snips/{week_ending}/{h}")
    def change_snip(week_ending: str, h: str, body: SnipChange) -> dict:
        """Edit a snip's text, sector or date. A confirmed snip goes back to unconfirmed."""
        day = snip_day(week_ending)
        try:
            snip_guard(day, h, body.sector)
            snip_store.update(day, h, text=body.text, sector=body.sector, date_text=body.date, root=d.snips_dir, sources_root=d.sources_dir)
        except snip_store.SnipError as exc:
            raise HTTPException(422, str(exc))
        return snip_view(day)

    @router.post("/api/snips/{week_ending}/{h}/confirm")
    def confirm_snip(week_ending: str, h: str) -> dict:
        """Save the snip's text as a source for its sector. Refused while it has an [unclear] mark."""
        day = snip_day(week_ending)
        try:
            snip_guard(day, h)
            snip_store.confirm(day, h, d.snips_dir, d.sources_dir)
        except (snip_store.SnipError, source_store.SourceError) as exc:
            raise HTTPException(422, str(exc))
        return snip_view(day)

    @router.delete("/api/snips/{week_ending}/{h}")
    def delete_snip(week_ending: str, h: str) -> dict:
        day = snip_day(week_ending)
        try:
            snip_guard(day, h)
            snip_store.remove(day, h, d.snips_dir, d.sources_dir)
        except snip_store.SnipError as exc:
            raise HTTPException(422, str(exc))
        return snip_view(day)

    return router
