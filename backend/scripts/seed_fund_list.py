from __future__ import annotations

import argparse
import sys
from pathlib import Path

import openpyxl

SHEET = "Money Market Performance"


def names(workbook: Path) -> list[str]:
    ws = openpyxl.load_workbook(workbook, read_only=True, data_only=True)[SHEET]
    rows, found = [], False
    for cells in ws.iter_rows(values_only=True):
        head = next((i for i, c in enumerate(cells) if isinstance(c, str) and c.strip().lower() == "fund manager"), None)
        if head is not None and head > 0 and not found:
            found, col = True, head
            continue
        if found:
            if isinstance(cells[col - 1], (int, float)) and isinstance(cells[col], str):
                rows.append(" ".join(cells[col].split()))
            elif rows:
                break
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Write the fund names of the Fixed Income mastersheet's fund table, one a line, to a text file "
                                                 "that can be pasted into the fund list editor. Names only, no rates. Run from backend/; the file is not for the repo.")
    parser.add_argument("mastersheet", type=Path)
    parser.add_argument("out", type=Path, help="the text file to write (keep it outside the repository)")
    args = parser.parse_args()
    found = names(args.mastersheet)
    if not found:
        sys.exit(f"No fund table (a 'Fund Manager' header with ranks beside it) was found in '{SHEET}'.")
    args.out.write_text("\n".join(found) + "\n", encoding="utf-8")
    print(f"{len(found)} fund names written.")
