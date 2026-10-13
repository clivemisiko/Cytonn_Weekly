"""Compare the two apps' screenshot sets (screenshots/parity/next and /vue, written by `npm run shots`).

    python e2e/compare_shots.py

Prints, per screenshot, both sizes and the share of pixels that differ, most different first; then every colour token
as each app resolves it in each theme, and the contrast ratio of the text and edge pairs the app uses. It is a guide
for where to look, not a verdict: the pages still have to be compared by eye. Needs Pillow.
"""
import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1] / "screenshots" / "parity"
NEXT, VUE = ROOT / "next", ROOT / "vue"

# (text or edge, surface, the least ratio it should reach). A third name is a tint: that share of it over the surface.
PAIRS = [
    ("foreground", "background", 4.5), ("foreground", "card", 4.5), ("foreground", "muted", 4.5),
    ("muted-foreground", "background", 4.5), ("muted-foreground", "card", 4.5), ("muted-foreground", "muted", 4.5),
    ("primary-foreground", "primary", 4.5), ("primary-foreground", "primary-hover", 4.5),
    ("link", "background", 4.5), ("link", "card", 4.5),
    ("band-foreground", "band", 4.5), ("band-muted", "band", 4.5),
    ("flag-fg", "background", 4.5), ("flag-fg", "card", 4.5), ("flag-fg", "card+flag", 4.5), ("flag-on", "flag", 4.5),
    ("warn-fg", "background", 4.5), ("warn-fg", "card", 4.5), ("warn-fg", "card+warn", 4.5),
    ("ok-fg", "background", 4.5), ("ok-fg", "card", 4.5), ("ok-fg", "card+ok", 4.5), ("ok-on", "ok", 4.5),
    ("dev-ink", "dev-a", 4.5), ("dev-ink", "dev-b", 4.5),
    ("input", "card", 3.0), ("input", "background", 3.0), ("ring", "background", 3.0), ("ring", "card", 3.0),
]


def rgb(text):
    nums = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", text)]
    return tuple(n * 255 for n in nums[:3]) if text.startswith("color(") else tuple(nums[:3])


def luminance(colour):
    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in colour)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def surface(tokens, name):
    if "+" not in name:
        return rgb(tokens[name])
    base, tint = (rgb(tokens[n]) for n in name.split("+"))
    return tuple(0.9 * b + 0.1 * t for b, t in zip(base, tint))  # the 10% tint the notices and chips use


def main():
    rows = []
    names = sorted(p.name for p in NEXT.glob("*.png"))
    missing = sorted(set(names) ^ {p.name for p in VUE.glob("*.png")})
    for name in names:
        if not (VUE / name).exists():
            continue
        a, b = Image.open(NEXT / name).convert("RGB"), Image.open(VUE / name).convert("RGB")
        if a.size != b.size:
            rows.append((100.0, name, a.size, b.size))
            continue
        diff = ImageChops.difference(a, b).convert("L").point(lambda v: 255 if v > 24 else 0)
        rows.append((100.0 * diff.histogram()[255] / (a.size[0] * a.size[1]), name, a.size, b.size))
    print(f"{len(rows)} screenshots compared; only in one set: {missing or 'none'}")
    for share, name, sa, sb in sorted(rows, reverse=True):
        note = "" if sa == sb else f"  SIZE next {sa[0]}x{sa[1]} vue {sb[0]}x{sb[1]}"
        print(f"  {share:6.2f}%  {name}{note}")

    tn, tv = (json.loads((d / "tokens.json").read_text()) for d in (NEXT, VUE))
    same = tn == tv
    print(f"\ncolour tokens resolved identically in both apps, both themes: {same} ({sum(len(v) for v in tn.values())} values)")
    if not same:
        for scheme in tn:
            for key in tn[scheme]:
                if tn[scheme][key] != tv[scheme].get(key):
                    print(f"  differs: {scheme} --{key}: next {tn[scheme][key]} vue {tv[scheme].get(key)}")
    worst = 0
    for scheme in ("light", "dark"):
        print(f"\ncontrast, {scheme} theme ({len(PAIRS)} pairs; the same in both apps when the tokens are):")
        for fg, bg, least in PAIRS:
            rn, rv = (ratio(rgb(t[scheme][fg]), surface(t[scheme], bg)) for t in (tn, tv))
            ok = rn >= least and rv >= least
            worst += not ok
            print(f"  {'ok  ' if ok else 'LOW '} {fg} on {bg}: next {rn:.2f}, vue {rv:.2f} (needs {least})")
    return 1 if (worst or not same) else 0


if __name__ == "__main__":
    sys.exit(main())
