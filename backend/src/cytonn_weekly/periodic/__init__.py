"""Sections of the quarterly, half-year and annual Markets Reviews (report_types.PERIODIC).

Each section is block-shaped (common/review.py) and built by a ``build_<section>_review(ctx)``
taking a ``periodic.common.PeriodContext``.  The structure each one follows is the real
issues', read on 2026-10-05 and recorded in CLAUDE.md ("Report types").  What a public
source supports is fetched or drafted with a citation; what does not is an explicit stub
(NotImplementedError with a ``*_BLOCKED_REASON`` and ``*_UNBLOCK``) shown to the
coordinator as an ``unavailable`` block.
"""
