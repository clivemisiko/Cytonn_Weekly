from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cytonn_weekly import db
from cytonn_weekly.env import load_env
from cytonn_weekly.history import importer
from cytonn_weekly.weekly.workbook import Workbook, WorkbookError


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Import the history sheets of the analysts' workbooks into the history store. Dry run unless --apply.")
    ap.add_argument("workbooks", nargs="+", type=Path, help=".xlsx files: the equities workbook and/or the fixed income mastersheet")
    ap.add_argument("--db", type=Path, help="a SQLite file (a scratch database); without it, the configured database")
    ap.add_argument("--apply", action="store_true", help="write the points the store does not hold yet, as confirmed imports")
    args = ap.parse_args(argv)
    load_env()
    kind, path = db.target(args.db)
    print(f"database: {kind}" + (f" ({path})" if path else "") + f"; {'APPLY' if args.apply else 'dry run, nothing is written'}")
    status = 0
    for file in args.workbooks:
        print(f"\n{file.name}")
        try:
            book = Workbook(file.read_bytes(), file.name)
        except (OSError, WorkbookError) as exc:
            print(f"  cannot open: {exc}")
            status = 1
            continue
        plan = importer.read_workbook(book)
        counts, new = importer.classify(args.db, plan)
        print("\n".join("  " + line for line in importer.report(plan, counts)))
        status = status or int(bool(plan.errors))
        if args.apply and new and not plan.errors:
            print(f"  wrote {importer.apply(args.db, plan)} points")
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
