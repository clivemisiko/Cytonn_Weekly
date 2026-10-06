"""KCB daily email extraction: STUB, blocked on the real sample emails.

Most of the Fixed Income section (T-bill/T-bond secondary activity, money market
performance, Kenya Eurobonds, the Kenya Shilling) is reported from KCB's daily
email, whose figures are split between the body text and a PDF attachment.  No
sample has been seen yet, so the extracted shape is deliberately left undefined:
writing fields now would be a guess at a schema, and the checker would then be
exact-matching against a guess.

What unblocks it: the 20 sample emails (body + attachment) requested from
Cytonn, plus an inbox or forwarding rule for the live feed.  With those, define
``KcbExtract`` from the real figures, write ``extract_kcb_email``, and
``build_fixed_income_review`` can be wired like the other sections, using
cbk_auctions.py as the independent second source for auction figures.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

BLOCKED_REASON = (
    "The weekly Fixed Income section is drafted from KCB's daily email, and none of the 20 requested "
    "sample emails has arrived, so its extraction cannot be written without guessing the format."
)
UNBLOCK = "The 20 KCB daily email samples (body and PDF attachment), then an inbox or forwarding rule for the live feed."


class KcbExtract:
    """The figures one KCB daily email carries.  Fields are defined from the real samples, not before."""


def extract_kcb_email(raw_email: str) -> Optional[KcbExtract]:
    # TODO: needs the 20 real KCB sample emails before the schema and parser can be written.
    raise NotImplementedError(BLOCKED_REASON)


def build_fixed_income_review(today: Optional[date] = None):
    """The full weekly Fixed Income run.  Not buildable until extract_kcb_email exists."""
    # TODO: wire KCB extract + cbk_auctions + mmf into a CoordinatorReview once extract_kcb_email is written.
    raise NotImplementedError(BLOCKED_REASON)
