"""The CMS publish stub (api/cms_publish.py): what it refuses, that it is blocked, and that it touches nothing.

Reviews are the helpers' real ones (tests/review_helpers.py, section_helpers.py,
periodic_helpers.py), approved the way a coordinator would.  Every call to the stub runs
inside ``sealed()``, which fails the test if anything opens a file for writing, changes
the file system, opens a database, connects a socket or starts an SMTP session.
"""

import ast
import builtins
import io
import os
import smtplib
import socket
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import cms_publish
from api.cms_publish import BLOCKED_REASON, UNBLOCK, PublishNotAllowed, local_pieces, publish_report
from api.main import create_app
from cytonn_weekly.digital_payments import review_store
from cytonn_weekly.digital_payments.coordinator_review import APPROVED, REJECTED
from cytonn_weekly.periodic import executive_summary
from tests import periodic_helpers as ph
from tests import section_helpers as sh
from tests.review_helpers import LocalFakeProvider, make_review

Q3 = "Q3'2026"
BACKEND = Path(__file__).parents[1]
REPO = BACKEND.parent


def approved(review, report_type="weekly", period=""):
    review.report_type, review.period = report_type, period
    for item in review.review_items:
        item.resolve("accept")
    review.decide(APPROVED)
    return review


def undecided(review, report_type="weekly", period=""):
    review.report_type, review.period = report_type, period
    return review


class MixedProvider(sh.FakeNarrativeProvider):
    """A section whose lead piece is a normal draft and whose SECOND piece was drafted by the local model."""

    def draft_piece(self, brief, *, start, end, today):
        piece = super().draft_piece(brief, start=start, end=end, today=today)
        if brief.id == "public_debt":
            piece.drafted_by = "local:phi4-mini"
        return piece


@contextmanager
def sealed(monkeypatch, tmp_path):
    """Run the body with every way out closed; afterwards, nothing was written and nothing was called."""
    touched = []

    def refuse(what):
        def refused(*args, **kwargs):
            touched.append(what)
            raise AssertionError(f"the publish stub must not use {what}")
        return refused

    real_open = builtins.open

    def read_only_open(file, mode="r", *args, **kwargs):
        if set(mode) & set("wax+"):
            refuse(f"open({file!r}, {mode!r})")()
        return real_open(file, mode, *args, **kwargs)

    with monkeypatch.context() as m:
        m.chdir(tmp_path)
        m.setattr(builtins, "open", read_only_open)
        m.setattr(io, "open", read_only_open)
        for name in ("mkdir", "makedirs", "remove", "unlink", "rename", "replace", "rmdir"):
            m.setattr(os, name, refuse(f"os.{name}"))
        m.setattr(sqlite3, "connect", refuse("sqlite3.connect"))
        m.setattr(socket.socket, "connect", refuse("socket.connect"))
        m.setattr(socket, "create_connection", refuse("socket.create_connection"))
        m.setattr(socket, "getaddrinfo", refuse("socket.getaddrinfo"))
        m.setattr(smtplib, "SMTP", refuse("smtplib.SMTP"))
        yield
    assert touched == []
    assert list(tmp_path.iterdir()) == []


@pytest.fixture
def publish(monkeypatch, tmp_path_factory):
    """publish_report, sealed; returns the exception it raised (it always raises)."""
    def call(report_type, period, reviews):
        with sealed(monkeypatch, tmp_path_factory.mktemp("cwd")):
            with pytest.raises(Exception) as exc:
                publish_report(report_type, period, reviews)
        return exc.value
    return call


# --- blocked ---------------------------------------------------------------------

def test_the_constants_say_what_blocks_it_and_what_unblocks_it():
    assert "no access to Cytonn's CMS and no credentials" in BLOCKED_REASON
    assert "the input the CMS expects is unconfirmed" in BLOCKED_REASON
    assert "finished PDF" in BLOCKED_REASON and "section text, headings or a manifest" in BLOCKED_REASON
    assert "who produces the PDF is unconfirmed" in BLOCKED_REASON
    for needed in ("CMS access and credentials from Cytonn", "written confirmation of who produces the PDF",
                   "what the CMS needs on the way in", "whether the upload is done through the admin pages behind SSO"):
        assert needed in UNBLOCK


def test_an_approved_weekly_digital_payments_review_reaches_the_blocked_error(publish):
    review = approved(make_review())
    assert "items" in review.section and "blocks" not in review.section      # the weekly Digital Payments shape
    err = publish("weekly", "", [review])
    assert type(err) is NotImplementedError
    assert str(err) == f"{BLOCKED_REASON} To unblock: {UNBLOCK}"


def test_approved_block_shaped_reviews_reach_the_blocked_error(publish):
    weekly = [approved(sh.equities_review()), approved(sh.real_estate_review()), approved(make_review())]
    assert "blocks" in weekly[0].section
    err = publish("weekly", "", weekly)
    assert type(err) is NotImplementedError and BLOCKED_REASON in str(err) and UNBLOCK in str(err)
    quarterly = [approved(build(), "quarterly", Q3) for build in ph.BUILDERS.values()]
    err = publish("quarterly", Q3, quarterly)
    assert type(err) is NotImplementedError and BLOCKED_REASON in str(err) and UNBLOCK in str(err)


# --- refusals, before the blocked error ----------------------------------------------

@pytest.mark.parametrize("nothing", [[], (), None])
def test_no_sections_is_refused(publish, nothing):
    err = publish("weekly", "", nothing)
    assert isinstance(err, PublishNotAllowed) and "no sections were given" in str(err)


def test_a_local_drafted_weekly_review_is_refused_naming_the_section_and_each_piece(publish):
    review = approved(make_review(LocalFakeProvider()))
    err = publish("weekly", "", [review])
    assert isinstance(err, PublishNotAllowed) and not isinstance(err, NotImplementedError)
    text = str(err)
    assert text.startswith("a dev-mode draft is never published.")
    assert "section 'digital_payments', piece 'Visa announces a thing' (local:phi4-mini)" in text
    assert "section 'digital_payments', piece 'outlook' (local:phi4-mini)" in text
    highlights = [i for i in review.section["items"] if i.get("kind") == "highlight"]
    assert len(highlights) == 4 and text.count("local:phi4-mini") == 4 + 1          # every highlight, and the outlook


def test_a_local_piece_that_is_not_the_lead_piece_is_refused(publish):
    normal = approved(ph.equities_review(), "quarterly", Q3)
    mixed = approved(ph.fixed_income_review(provider=MixedProvider()), "quarterly", Q3)
    pieces = [b for b in mixed.section["blocks"] if b["kind"] == "narrative"]
    assert [b["drafted_by"] for b in pieces] == ["fake:test", "local:phi4-mini"]     # the lead piece is a normal draft
    err = publish("quarterly", Q3, [normal, mixed])
    assert isinstance(err, PublishNotAllowed)
    assert str(err) == ("a dev-mode draft is never published. Drafted by the local model: section 'fixed_income', "
                        "piece 'Government borrowing and public debt: a development' (local:phi4-mini)")


def test_an_executive_summary_composed_from_a_section_with_a_local_piece_is_refused(publish, tmp_path):
    db = tmp_path / "app.db"
    for slug, build in ph.BUILDERS.items():
        review = approved(build(provider=MixedProvider()) if slug == "fixed_income" else build(), "quarterly", Q3)
        review_store.save_review(review, section=review.section["section"], db_path=db)
    summary = approved(executive_summary.build_executive_summary_review(ph.ctx(db_path=db)), "quarterly", Q3)
    assert {b["drafted_by"] for b in summary.section["blocks"]} == {"fake:test"}     # the carried text is all normal
    err = publish("quarterly", Q3, [summary])
    assert isinstance(err, PublishNotAllowed)
    assert ("section 'executive_summary', piece 'Government borrowing and public debt: a development' "
            "(local:phi4-mini)") in str(err)


def test_a_local_draft_is_refused_before_its_approval_is_even_looked_at(publish):
    review = undecided(make_review(LocalFakeProvider()))
    err = publish("weekly", "", [approved(sh.equities_review()), review])
    assert isinstance(err, PublishNotAllowed) and str(err).startswith("a dev-mode draft is never published.")


def test_a_review_that_is_not_approved_is_refused(publish):
    good = approved(sh.equities_review())
    err = publish("weekly", "", [good, undecided(make_review())])
    assert isinstance(err, PublishNotAllowed)
    assert "'digital_payments'" in str(err) and "is still in progress, not approved" in str(err)
    rejected = undecided(sh.real_estate_review())
    rejected.decide(REJECTED)
    err = publish("weekly", "", [good, rejected])
    assert isinstance(err, PublishNotAllowed) and "'real_estate'" in str(err) and "is rejected, not approved" in str(err)


def test_a_decision_field_alone_is_not_approval(publish):
    review = undecided(make_review())
    review.decision = APPROVED                   # set by hand; no item was resolved
    err = publish("weekly", "", [review])
    assert isinstance(err, PublishNotAllowed) and "not every item is resolved and accepted" in str(err)


def test_a_section_of_another_report_or_period_is_refused(publish):
    weekly = approved(sh.equities_review())
    err = publish("quarterly", Q3, [approved(ph.equities_review(), "quarterly", Q3), weekly])
    assert isinstance(err, PublishNotAllowed) and "belongs to the weekly report (no period)" in str(err)
    err = publish("quarterly", "Q1'2026", [approved(ph.equities_review(), "quarterly", Q3)])
    assert isinstance(err, PublishNotAllowed) and "belongs to the quarterly report (Q3'2026)" in str(err)


def test_local_pieces_reads_every_shape():
    assert list(local_pieces(approved(make_review()).section)) == []
    assert list(local_pieces({"blocks": [{"id": "b1", "drafted_by": "local:m"}, {"headline": "H", "drafted_by": "fake:x"}],
                              "not_covered": [{"dev_pieces": [{"piece": "P", "drafted_by": "local:m"}]}]})) == [
        ("b1", "local:m"), ("P", "local:m")]


# --- unreachable -------------------------------------------------------------------

def test_the_stub_imports_nothing_that_could_reach_out():
    tree = ast.parse(Path(cms_publish.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module)
    assert imported == {"__future__", "typing", "cytonn_weekly.digital_payments.coordinator_review",
                        "cytonn_weekly.report_sections"}


def test_nothing_in_the_app_can_reach_the_stub(tmp_path):
    sources = [p for folder in ("api", "src", "scripts") for p in (BACKEND / folder).rglob("*.py")]
    sources += [p for ext in ("*.ts", "*.tsx") for p in (REPO / "frontend" / "src").rglob(ext)]
    assert len(sources) > 50
    mentions = [p for p in sources if "cms_publish" in p.read_text(encoding="utf-8", errors="replace")
                or "publish_report" in p.read_text(encoding="utf-8", errors="replace")]
    assert mentions == [Path(cms_publish.__file__)]
    app = create_app(db_path=tmp_path / "app.db", load_dotenv=False)
    paths = [route.path.lower() for route in app.routes]
    assert paths and not [p for p in paths if "publish" in p or "cms" in p]
    assert TestClient(app).post("/api/publish").status_code == 404
