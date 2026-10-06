"""Email the latest approved Word summary of a report section to its insight recipients (Edwin and Liz).

Sends REAL email once real SMTP credentials are in .env, so it never sends by default:

    python scripts/send_weekly_summary.py                  # preview only: what would be sent, to whom
    python scripts/send_weekly_summary.py --yes            # actually send
    python scripts/send_weekly_summary.py digital_payments --yes

Run from backend/ after `pip install -e .`.  SMTP settings and
CYTONN_SUMMARY_RECIPIENTS come from the repo-root .env (see .env.example).

Refuses, sending nothing and exiting non-zero, when the section's latest saved review
is missing, undecided or rejected, or when any part of it was drafted by the local
dev-mode model (``drafted_by`` starting "local:").  delivery.py and summary.py
enforce the same rules on the send path itself; the dev-mode check is repeated here
because this script is where a person can trigger a send by habit, so it must refuse
before printing anything that looks sendable.

Only sections with a Word summary renderer are accepted.  summary.py renders the
Digital Payments section only, so that is the one choice today.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Iterator, Optional, Union

from cytonn_weekly.digital_payments import delivery, review_store, summary

# Sections summary.py can render.  Others have reviews but no Word summary yet.
SUMMARY_SECTIONS = ("digital_payments",)
DEV_PREFIX = "local:"


def drafted_by_values(content: Any) -> Iterator[str]:
    """Every ``drafted_by`` value anywhere in a review's section content, whatever its shape."""
    if isinstance(content, dict):
        for key, value in content.items():
            if key == "drafted_by" and value is not None:
                yield str(value)
            else:
                yield from drafted_by_values(value)
    elif isinstance(content, list):
        for value in content:
            yield from drafted_by_values(value)


def main(argv: Optional[list[str]] = None, *, db_path: Optional[Union[Path, str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("section", nargs="?", default="digital_payments", choices=SUMMARY_SECTIONS,
                        help="report section slug (default: digital_payments)")
    parser.add_argument("--yes", action="store_true",
                        help="actually send the email; without it the script only previews")
    parser.add_argument("--out", type=Path, default=None,
                        help="where to write the .docx (default: data/summaries/)")
    args = parser.parse_args(argv)

    review = review_store.load_latest_review(args.section, db_path=db_path)
    if review is None:
        print(f"REFUSED: no saved review for section {args.section!r}; nothing to send.")
        return 1

    status = review.decision or "undecided (review in progress)"
    drafters = sorted(set(drafted_by_values(review.section)))
    dev = [d for d in drafters if d.startswith(DEV_PREFIX)]

    print(f"Section:      {args.section}")
    print(f"Review run:   {review.run_id}, week {review.section.get('week_start')} to {review.section.get('week_end')}")
    print(f"Approval:     {status}" + (f" ({review.decided_at})" if review.decided_at else ""))
    print(f"Drafted by:   {', '.join(drafters) or '(none recorded)'}")

    if dev:
        print(f"\nREFUSED: this review was drafted in DEV MODE ({', '.join(dev)}). "
              "A dev-mode draft is never sent to a real recipient.")
        return 1
    if review.decision != "approved":
        print("\nREFUSED: only an approved review is summarized and sent.")
        return 1

    try:
        recipients = delivery.resolve_recipients()
        smtp = delivery.smtp_settings()
    except ValueError as exc:
        print(f"\nREFUSED: delivery is not configured: {exc}")
        return 1

    print(f"Recipients:   {', '.join(recipients)}")
    print(f"From:         {smtp.sender} via {smtp.host}:{smtp.port}")

    if not args.yes:
        print("\nPreview only; nothing was written or sent.  Re-run with --yes to send this summary.")
        return 0

    # deliver_latest_summary() loads the latest review again and re-applies the approval
    # and dev-mode guards itself.  If a newer run was saved between this preview and the
    # send, it would send that one (only if it too is approved and not dev mode), so the
    # path it returns is checked against the run previewed above.
    path = delivery.deliver_latest_summary(section=args.section, db_path=db_path, out_path=args.out)
    print(f"\nSent {path} to {', '.join(recipients)}.")
    if args.out is None and path != summary.default_summary_path(review):
        print(f"WARNING: a newer review than run {review.run_id} was saved during the send; "
              f"the summary sent was {path.name}, not the one previewed.")
        return 2
    return 0


if __name__ == "__main__":
    from cytonn_weekly.env import load_env

    load_env()  # before anything reads os.environ (SMTP settings, recipients)
    sys.exit(main())
