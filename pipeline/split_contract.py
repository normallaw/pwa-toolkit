#!/usr/bin/env python3
"""
Split the extracted PWA markdown into per-document files under sections/, loa/
and mou/.

Documents are identified from the running page header that appears at the top of
every page ("Section 23 - Scheduling", "LOA #23-02 - Global Scope", ...), and
each page is assigned to the document it names, forward-filling across pages
whose header is absent (tab dividers, signature pages, tables). Titles come from
the table of contents, which is the only place that names every document
consistently — running headers are sometimes truncated (LOA #13-05) or
title-less (MOU #25-01).

Everything here is derived from the document itself, so it re-derives correctly
on the next revision rather than needing hand-maintained line-number anchors.

Also writes `<data>/INDEX.md` — the navigation index the `contract` skill reads.
It is generated here, from the ingested edition, rather than kept in the
repository, both so it can never drift from the text it describes and because a
full listing of the contract's contents is not ours to publish.

Usage:
    python3 pipeline/split_contract.py            # write files
    python3 pipeline/split_contract.py --dry-run  # print the page->document map only
"""

import argparse
import re
from datetime import date
from pathlib import Path

from config import DATA_DIR, HANDBOOKS_DIR, INDEX_MD, LOA_DIR, MOU_DIR, OUT_MD, SECTIONS_DIR

PAGE_RE = re.compile(r"\n<!-- page (\d+) \| (\w+) -->\n")

# Header forms, matched only against the first few lines of a page.
SECTION_HDR = re.compile(r"^#*\s*Section\s+(\d{1,2})\s*[–—-]\s*(.+?)\s*$", re.I)
DIVIDER_HDR = re.compile(r"^\s*\d*\s*SECTION\s+(\d{1,2})\s*$", re.I)
# Title is optional: several documents (e.g. MOU #25-01, LOA #13-04) carry only
# the bare number in the running header and name themselves further down.
LOA_HDR = re.compile(r"^#*\s*LOA\s*#\s*([\d]{1,2}(?:-\d{2})?)\s*[–—-]?\s*(.*?)\s*$", re.I)
MOU_HDR = re.compile(r"^#*\s*MOU\s*#\s*([\d]{1,2}(?:-\d{2})?)\s*[–—-]?\s*(.*?)\s*$", re.I)

# Table of contents entries, used as the authoritative source of titles.
TOC_SECTION = re.compile(r"^(\d{1,2})\.\s+(.+?)\s*$")
TOC_DOC = re.compile(r"^(LOA|MOU)\s*#\s*([\d]{1,2}(?:-\d{2})?)\s+(.+?)\s*$", re.I)

HEADER_SCAN_LINES = 4  # running header lives at the very top of the page
TOC_PAGES = range(3, 6)
FIRST_DOC_PAGE = 6  # everything before the Section 1 tab divider is front matter


def slug(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[&]", " and ", text)
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


def parse_pages(src: str) -> dict[int, str]:
    parts = PAGE_RE.split(src)
    return {int(parts[i]): parts[i + 2] for i in range(1, len(parts), 3)}


def parse_toc(pages: dict[int, str]) -> dict[tuple[str, str], str]:
    """Titles for every document, taken from the table of contents.

    Entries that wrap onto a second line are joined back together.
    """
    titles: dict[tuple[str, str], str] = {}
    last_key: tuple[str, str] | None = None
    for n in TOC_PAGES:
        if n not in pages:
            continue
        for line in pages[n].splitlines():
            stripped = line.strip()
            if not stripped or stripped.lower().startswith("table of contents"):
                continue
            m = TOC_SECTION.match(stripped)
            if m:
                last_key = ("section", m.group(1))
                titles[last_key] = m.group(2)
                continue
            m = TOC_DOC.match(stripped)
            if m:
                last_key = (m.group(1).lower(), m.group(2))
                titles[last_key] = m.group(3)
                continue
            # Continuation of the previous entry: indented, no number of its own.
            if last_key and line.startswith("  ") and not stripped.startswith(("LOA", "MOU")):
                titles[last_key] = f"{titles[last_key]} {stripped}"
    return titles


def identify(page: str) -> tuple[str, str, str] | None:
    """Return (kind, number, title) if this page names a document, else None."""
    lines = [l.strip() for l in page.splitlines() if l.strip()][:HEADER_SCAN_LINES]
    for line in lines:
        m = SECTION_HDR.match(line)
        if m:
            return ("section", m.group(1), m.group(2))
        m = LOA_HDR.match(line)
        if m:
            return ("loa", m.group(1), m.group(2))
        m = MOU_HDR.match(line)
        if m:
            return ("mou", m.group(1), m.group(2))
    # Tab-divider pages announce the upcoming section without a title.
    for line in lines:
        m = DIVIDER_HDR.match(line)
        if m:
            return ("section", m.group(1), "")
    return None


def write_index(records: list[dict], front: list[int], total_pages: int) -> None:
    """Write the navigation index the `contract` skill reads.

    Regenerated from scratch on every split, so it can never describe an edition
    other than the one sitting in the data directory.
    """
    counts = {k: sum(1 for r in records if r["kind"] == k) for k in ("section", "loa", "mou")}
    lines = [
        "# Contract index",
        "",
        "Generated by `pipeline/split_contract.py` from the ingested PDF. Do not edit by",
        "hand — it is rewritten on every ingestion.",
        "",
        f"Ingested {date.today().isoformat()} · {total_pages} pages · "
        f"{counts['section']} sections · {counts['loa']} LOAs · {counts['mou']} MOUs · "
        f"{len(front)} pages of front matter",
        "",
        "Check the LOA and MOU counts against the contract's own inventory in the final",
        "section (Section 29 C. in the Delta PWA). They must match exactly.",
    ]

    headings = {
        "section": ("Sections", "Section"),
        "loa": ("Letters of Agreement", "LOA"),
        "mou": ("Memoranda of Understanding", "MOU"),
    }
    for kind, (heading, label) in headings.items():
        rows = [r for r in records if r["kind"] == kind]
        if not rows:
            continue
        lines += ["", f"## {heading}", "",
                  f"| {label} | Title | Pages | File |",
                  "|---|---|---|---|"]
        for r in rows:
            pages = r["first"] if r["first"] == r["last"] else f"{r['first']}–{r['last']}"
            lines.append(f"| {r['num']} | {r['title']} | {pages} | `{r['file']}` |")

    if front:
        lines += ["", "## Front matter", "",
                  f"Pages {front[0]}–{front[-1]} — title page and table of contents. "
                  f"`sections/00_front_matter.txt`"]

    handbooks = sorted(HANDBOOKS_DIR.glob("*.md")) if HANDBOOKS_DIR.is_dir() else []
    lines += ["", "## Reference handbooks", ""]
    if handbooks:
        lines.append("Explanatory guides, **not** binding contract text — see the skill's "
                     "authority note.")
        lines.append("")
        for h in handbooks:
            lines.append(f"- `{h.relative_to(DATA_DIR).as_posix()}`")
    else:
        lines.append("None ingested. See `pipeline/transcribe_handbooks.py`.")

    INDEX_MD.parent.mkdir(parents=True, exist_ok=True)
    INDEX_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    ap.add_argument("--dry-run", action="store_true",
                    help="print the page->document map without writing files")
    ap.add_argument("--input", type=Path, default=OUT_MD,
                    help=f"merged extraction to split (default: {OUT_MD})")
    args = ap.parse_args()

    if not args.input.exists():
        raise SystemExit(
            f"{args.input} not found — run `python3 pipeline/extract_contract.py` first."
        )

    pages = parse_pages(args.input.read_text(encoding="utf-8"))
    titles = parse_toc(pages)

    # ── Assign every page to a document, forward-filling untitled pages ───────
    assignment: dict[int, tuple[str, str]] = {}
    current: tuple[str, str] | None = None
    for n in sorted(pages):
        if n < FIRST_DOC_PAGE:  # title page + TOC, which names every document
            continue
        ident = identify(pages[n])
        if ident:
            kind, num, title = ident
            key = (kind, num)
            # The TOC wins; a header title is only a fallback for anything it missed.
            if title and key not in titles:
                titles[key] = title
            current = key
        if current:
            assignment[n] = current

    # ── Group pages per document, in page order ──────────────────────────────
    docs: dict[tuple[str, str], list[int]] = {}
    for n in sorted(assignment):
        docs.setdefault(assignment[n], []).append(n)

    front = [n for n in sorted(pages) if n not in assignment]

    if args.dry_run:
        print(f"front matter: {len(front)} pages {front}")
        for (kind, num), pgs in docs.items():
            title = titles.get((kind, num), "(untitled)")
            print(f"{kind:8s} #{num:6s} pages {pgs[0]:>3}-{pgs[-1]:<3} ({len(pgs):>3})  {title[:60]}")
        return

    for d in (SECTIONS_DIR, LOA_DIR, MOU_DIR):
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob("*.txt"):
            old.unlink()

    def write(path: Path, heading: str, page_nums: list[int]) -> None:
        body = "\n".join(pages[n].rstrip() for n in page_nums)
        path.write_text(f"{heading}\n\n{body}\n", encoding="utf-8")

    if front:
        write(SECTIONS_DIR / "00_front_matter.txt", "# Front Matter", front)

    records: list[dict] = []
    for (kind, num), pgs in docs.items():
        title = titles.get((kind, num), "")
        if kind == "section":
            name = f"section_{int(num):02d}_{slug(title)}.txt"
            heading = f"# Section {num} – {title}"
            out = SECTIONS_DIR / name
        else:
            name = f"{kind}_{num.replace('-', '_')}_{slug(title)}.txt"
            heading = f"# {kind.upper()} #{num} – {title}"
            out = (LOA_DIR if kind == "loa" else MOU_DIR) / name
        write(out, heading, pgs)
        records.append({
            "kind": kind, "num": num, "title": title,
            "file": out.relative_to(DATA_DIR).as_posix(),
            "first": pgs[0], "last": pgs[-1],
        })

    write_index(records, front, len(pages))

    written = {k: sum(1 for r in records if r["kind"] == k) for k in ("section", "loa", "mou")}
    print(f"front matter pages: {len(front)}")
    for kind, count in written.items():
        print(f"{kind}s written: {count}")
    print(f"wrote {INDEX_MD}")


if __name__ == "__main__":
    main()
