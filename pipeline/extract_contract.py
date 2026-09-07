#!/usr/bin/env python3
"""
Extract the PWA PDF to a single markdown file, one page at a time.

The PDF carries a clean embedded text layer for the large majority of its pages,
so those are lifted directly with `pdftotext -layout` — instant, lossless, and
with the original layout and left-margin line numbers preserved. Only two kinds
of page need real OCR:

  1. image-only pages  – the composite pay tables in Section 3, plus a number of
                         appendix/signature pages, are scanned images with no
                         text layer at all.
  2. scrambled pages   – some LOA/MOU pages use a custom font encoding that
                         pdftotext renders as mojibake ("/2$" for "LOA") and
                         which drops all spaces, so the page cannot be recovered
                         by unshifting alone.

Those pages are rasterized and transcribed with Claude vision, concurrently, and
merged back in page order. Pages where only the running header or a caption is
in the broken font are repaired in place instead (see `decode_mojibake`), so
they keep their exact text layer.

Output is written to `<data>/extracted/live-contract-full.md` with a provenance
marker above every page (`<!-- page N | text|ocr -->`), which is what
`split_contract.py` reads.

Usage:
    python3 pipeline/extract_contract.py            # full run
    python3 pipeline/extract_contract.py --dry-run  # classify pages only, no API calls
"""

import argparse
import base64
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from config import (
    ANTHROPIC_VERSION,
    API_URL,
    MODEL,
    OCR_CACHE,
    OUT_MD,
    PAGE_IMG_DIR,
    PDF,
    require_api_key,
    require_pdf,
)

DPI = 200
MAX_WORKERS = 8
SPARSE_CHAR_THRESHOLD = 400
MAX_RETRIES = 5

PROMPT = (
    "Transcribe this page of an airline pilot working agreement to clean, faithful "
    "markdown. Preserve headings, numbered/lettered list structure, and bold/italic "
    "emphasis. Render any table as a proper markdown table — these pages often carry "
    "pay-rate tables where every cell value matters, so transcribe every number exactly "
    "and do not summarize, round, or omit rows or columns. Keep the left-margin line "
    "numbers out of the output. Do not add commentary, headers, or notes of your own — "
    "output only the transcribed page content."
)

COMMON_WORDS = re.compile(r"\b(the|and|of|to|will|pilot|Company|be|for|in|a)\b", re.I)


def unshift(s: str) -> str:
    """Undo the custom-font +29 character shift used on the scrambled pages."""
    return "".join(chr(ord(c) + 29) if 0x21 <= ord(c) <= 0x62 else c for c in s)


TOKEN = re.compile(r"[\x21-\x62]+")
VOCAB_WORD = re.compile(r"[A-Za-z]{4,}")   # words admitted when learning the vocabulary
MATCH_WORD = re.compile(r"[A-Za-z]{3,}")   # words tested when decoding a token

# Short document-specific terms that the frequency filter would otherwise miss.
SEED_VOCAB = {"loa", "mou", "pwa", "rma", "alpa", "mec", "inc", "exhibit"}

# Real decoded text only ever lands on letters, digits and ordinary punctuation.
# Anything else means the token was plain text that merely happened to unshift
# into something word-shaped — e.g. the rest-facility code "4A/2D", which
# unshifts to "Q^LOa" and would otherwise match on "loa".
PLAUSIBLE_DECODE = re.compile(r"^[A-Za-z0-9 .,;:()\[\]'\"“”‘’\-–—/#&%$*+!?]+$")


def build_vocab(clean_pages: list[str]) -> set[str]:
    """Vocabulary of the document, learned from its soundly-extracted pages.

    Used to decide whether unshifting a token reveals real English. Built only
    from clean pages so that repeated mojibake ("3LORW") can never enter it.
    """
    counts: dict[str, int] = {}
    for page in clean_pages:
        for w in VOCAB_WORD.findall(page):
            w = w.lower()
            counts[w] = counts.get(w, 0) + 1
    return {w for w, c in counts.items() if c >= 5} | SEED_VOCAB


def decode_mojibake(text: str, vocab: set[str]) -> str:
    """Recover custom-font runs in an otherwise-sound text layer.

    Some pages mix normal text with runs in the broken font — typically the
    running header and a caption, while the body extracts fine. Those runs are
    recoverable exactly, which beats sending an otherwise-perfect page to OCR.

    The encoding shifts every character down by 29 and writes the space as
    \\x03. Decoding cannot simply be applied to every run, because plain text
    shares the same character range: real words ("UNDERSTANDING"), years
    ("2026") and the margin line numbers would all be mangled. A token is
    therefore only decoded when unshifting it actually reveals a word this
    document uses. Short tokens carry too little signal to judge on their own,
    so they follow the decision made for the token before them — which is what
    turns "([KLELW $" into "Exhibit A" rather than "Exhibit $".
    """
    out_lines = []
    for line in text.split("\n"):
        prev_decoded = False

        def repl(m: re.Match) -> str:
            nonlocal prev_decoded
            token = m.group(0)
            shifted = "".join(
                chr(ord(c) + 29) if 0x21 <= ord(c) <= 0x62 else c for c in token
            )
            if (PLAUSIBLE_DECODE.match(shifted)
                    and any(w.lower() in vocab for w in MATCH_WORD.findall(shifted))):
                prev_decoded = True
            elif not (prev_decoded and len(token) <= 3):
                prev_decoded = False
                return token
            return shifted

        out_lines.append(TOKEN.sub(repl, line))

    # Control characters carry no legitimate meaning in extracted text (bar
    # tab/newline), so wherever they survive they are encoded glyphs and can be
    # shifted unconditionally: \x03 is the space, \x06 "#", \x14 "1". This runs
    # after the token pass so that already-decoded text is not shifted twice.
    decoded = "".join(
        chr(ord(c) + 29) if 0x03 <= ord(c) <= 0x1f and c not in "\t\n\r" else c
        for c in "\n".join(out_lines)
    )
    # The en dash of these headers maps to a glyph outside the shifted range.
    return decoded.replace("±", "–")


def load_pages(pdf: Path) -> list[str]:
    text = subprocess.run(
        ["pdftotext", "-layout", str(pdf), "-"],
        capture_output=True, text=True, check=True,
    ).stdout
    pages = text.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    return pages


def classify(pages: list[str]) -> dict[int, str]:
    """Return {page_number: reason} for pages that need vision OCR."""
    needs = {}
    for i, page in enumerate(pages, 1):
        body = "\n".join(l for l in page.splitlines() if l.strip())
        chars = len(re.sub(r"\s", "", body))
        raw_hits = len(COMMON_WORDS.findall(body))
        dec_hits = len(COMMON_WORDS.findall(unshift(body)))
        if dec_hits > raw_hits * 2 and dec_hits > 3:
            needs[i] = "scrambled"
        elif chars < SPARSE_CHAR_THRESHOLD:
            needs[i] = "sparse"
    return needs


def rasterize(pdf: Path, page_no: int) -> Path:
    PAGE_IMG_DIR.mkdir(parents=True, exist_ok=True)
    existing = sorted(PAGE_IMG_DIR.glob(f"p{page_no:04d}-*.png"))
    if existing:
        return existing[0]
    prefix = PAGE_IMG_DIR / f"p{page_no:04d}"
    subprocess.run(
        ["pdftoppm", "-png", "-r", str(DPI),
         "-f", str(page_no), "-l", str(page_no), str(pdf), str(prefix)],
        check=True,
    )
    return sorted(PAGE_IMG_DIR.glob(f"p{page_no:04d}-*.png"))[0]


def transcribe(pdf: Path, api_key: str, page_no: int) -> tuple[int, str]:
    """Transcribe one page with Claude vision, using the cache when present.

    Calls the Messages API over plain HTTP rather than through the `anthropic`
    SDK. The SDK is a fine choice here and the payload below is the same one it
    would send; raw HTTP simply keeps this script free of a version constraint —
    anthropic 0.46.0 against pydantic 2.13.4 fails to deserialize responses,
    erroring with "'typing.Union' object has no attribute '__discriminator__'"
    on a majority of concurrent calls.
    """
    cached = OCR_CACHE / f"p{page_no:04d}.md"
    if cached.exists():
        text = cached.read_text(encoding="utf-8")
        print(f"  page {page_no}: cached ({len(text)} chars)", flush=True)
        return page_no, text

    img = rasterize(pdf, page_no)
    b64 = base64.standard_b64encode(img.read_bytes()).decode()
    payload = {
        "model": MODEL,
        "max_tokens": 8192,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": "image/png", "data": b64}},
                {"type": "text", "text": PROMPT},
            ],
        }],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    for attempt in range(MAX_RETRIES):
        try:
            r = httpx.post(API_URL, headers=headers, json=payload, timeout=180.0)
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
            body = r.json()
            text = "".join(b.get("text", "") for b in body["content"]
                           if b.get("type") == "text")
            OCR_CACHE.mkdir(parents=True, exist_ok=True)
            cached.write_text(text, encoding="utf-8")
            print(f"  page {page_no}: ok ({len(text)} chars)", flush=True)
            return page_no, text
        except Exception as e:  # transient overload / rate limit
            if attempt == MAX_RETRIES - 1:
                print(f"  page {page_no}: FAILED {e}", flush=True)
                return page_no, f"<!-- OCR FAILED for page {page_no}: {e} -->"
            wait = 2 ** attempt * 5
            print(f"  page {page_no}: retry in {wait}s ({e})", flush=True)
            time.sleep(wait)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    ap.add_argument("--dry-run", action="store_true",
                    help="classify pages and report, without calling the API")
    ap.add_argument("--pdf", type=Path, default=PDF, help=f"source PDF (default: {PDF})")
    ap.add_argument("--workers", type=int, default=MAX_WORKERS,
                    help=f"concurrent OCR requests (default: {MAX_WORKERS})")
    args = ap.parse_args()

    pdf = require_pdf(args.pdf)
    pages = load_pages(pdf)
    needs = classify(pages)
    print(f"total pages: {len(pages)}")
    print(f"pages needing OCR: {len(needs)} "
          f"({sum(1 for v in needs.values() if v == 'scrambled')} scrambled, "
          f"{sum(1 for v in needs.values() if v == 'sparse')} sparse)")
    if args.dry_run:
        for p, reason in sorted(needs.items()):
            print(f"  p{p}: {reason}")
        return

    api_key = require_api_key()

    print(f"transcribing {len(needs)} pages with {MODEL} ({args.workers} workers)...")
    ocr: dict[int, str] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for page_no, text in pool.map(
            lambda p: transcribe(pdf, api_key, p), sorted(needs)
        ):
            ocr[page_no] = text

    failures = [p for p, t in ocr.items() if t.startswith("<!-- OCR FAILED")]
    if failures:
        print(f"\nWARNING: {len(failures)} page(s) failed OCR: {failures}")

    vocab = build_vocab([p for i, p in enumerate(pages, 1) if i not in needs])

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    with OUT_MD.open("w", encoding="utf-8") as f:
        for i, page in enumerate(pages, 1):
            source = "ocr" if i in ocr else "text"
            f.write(f"\n<!-- page {i} | {source} -->\n\n")
            f.write(ocr[i] if i in ocr else decode_mojibake(page, vocab).rstrip())
            f.write("\n")
    print(f"\nwrote {OUT_MD} ({OUT_MD.stat().st_size:,} bytes)")

    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
