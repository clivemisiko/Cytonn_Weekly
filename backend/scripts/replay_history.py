from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cytonn_weekly.history import importer, replay
from cytonn_weekly.weekly.workbook import Workbook, WorkbookError


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Replay the stored history against the equities workbook's own cells: for each week, the figures the "
                                             "builders would read from the store (CYTONN_HISTORY_READS=on) against the workbook's. Prints no value.")
    ap.add_argument("equities", type=Path, help="the equities workbook (.xlsx)")
    ap.add_argument("--db", type=Path, required=True, help="a SQLite file: a scratch database (this script never uses the configured one)")
    ap.add_argument("--fill", nargs="*", type=Path, metavar="XLSX", help="first import these workbooks (the equities workbook is always one) into the scratch database")
    ap.add_argument("--all", action="store_true", help="print every week's line, not only the failures and skips")
    args = ap.parse_args(argv)
    try:
        book = Workbook(args.equities.read_bytes(), args.equities.name)
    except (OSError, WorkbookError) as exc:
        print(f"{args.equities.name}: cannot open: {exc}")
        return 1
    if args.fill is not None:
        for file in [args.equities, *args.fill]:
            plan = importer.read_workbook(book if file == args.equities else Workbook(file.read_bytes(), file.name))
            print(f"{file.name}: imported {importer.apply(args.db, plan)} points into {args.db.name}")
    lines = replay.run(book, args.db)
    for line in lines:
        if args.all or line.status != "PASS":
            size = "" if line.difference is None else f" difference {line.difference:.6f}"
            print(f"{line.week}  {line.series}  {line.check}  {line.status}{size}" + (f"  ({line.note})" if line.note else ""))
    print()
    print("\n".join(replay.summary(lines)))
    failed = sum(line.status == "FAIL" for line in lines)
    print(f"\n{sum(line.status == 'PASS' for line in lines)} PASS, {failed} FAIL, {sum(line.status == 'SKIP' for line in lines)} SKIP")
    return int(failed > 0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
