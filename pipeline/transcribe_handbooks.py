#!/usr/bin/env python3
"""
Transcribe reference handbooks to markdown with Claude vision, via the Message
Batches API.

The handbooks are screenshot-heavy — much of their substance is text baked into
images of the bidding and scheduling software — so unlike the PWA there is no
usable text layer to lift. Every page is rasterized and transcribed. Batch
requests run asynchronously at half the standard price, which suits a job of a
few hundred pages that nobody is waiting on.

Input:  every PDF in `<data>/original/handbooks/`
Output: `<data>/handbooks/<name>.md`, one file per PDF, with `<!-- page N -->`
        provenance markers

Usage:
    python3 pipeline/transcribe_handbooks.py submit    # rasterize + submit, save batch ids
    python3 pipeline/transcribe_handbooks.py poll      # poll until every batch finishes
    python3 pipeline/transcribe_handbooks.py collect   # assemble results into handbooks/
"""

import argparse
import base64
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

from config import (
    EXTRACTED_DIR,
    HANDBOOKS_DIR,
    MODEL,
    ORIGINAL_DIR,
    PAGE_IMG_DIR,
    require_api_key,
)

HANDBOOK_PDF_DIR = ORIGINAL_DIR / "handbooks"
STATE_FILE = EXTRACTED_DIR / "handbook_batches.json"

DPI = 150
POLL_INTERVAL = 60

PROMPT = (
    "Transcribe this document page to clean, faithful markdown. "
    "Preserve headings, lists, tables, and bold/italic emphasis as markdown. "
    "This page may contain embedded screenshots of scheduling/bidding software — "
    "transcribe any readable text within those screenshots too (labels, field values, "
    "table contents, button text), describing the screenshot briefly only if some part "
    "of it is genuinely illegible. Do not add commentary, headers, or notes of your own — "
    "output only the transcribed page content."
)


def slug(text: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")


def discover_docs() -> list[dict]:
    """One entry per handbook PDF found in `original/handbooks/`."""
    if not HANDBOOK_PDF_DIR.is_dir():
        raise SystemExit(
            f"{HANDBOOK_PDF_DIR} not found.\n"
            f"Put the handbook PDFs there (one file per handbook), or point "
            f"PWA_DATA_DIR at the directory that holds them."
        )
    pdfs = sorted(HANDBOOK_PDF_DIR.glob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"No PDFs in {HANDBOOK_PDF_DIR}.")
    return [
        {
            "name": slug(p.stem),
            "pdf": p,
            "output": HANDBOOKS_DIR / f"{slug(p.stem)}.md",
            "title": p.stem,
        }
        for p in pdfs
    ]


def rasterize(pdf_path: Path, name: str) -> list[Path]:
    out_dir = PAGE_IMG_DIR / name
    out_dir.mkdir(parents=True, exist_ok=True)
    # Skip if already rasterized, so a re-submit after a failure is cheap.
    existing = sorted(out_dir.glob("page-*.png"))
    if existing:
        print(f"[{name}] reusing {len(existing)} already-rasterized page images")
        return existing
    print(f"[{name}] rasterizing {pdf_path.name} at {DPI} DPI...")
    subprocess.run(
        ["pdftoppm", "-png", "-r", str(DPI), str(pdf_path), str(out_dir / "page")],
        check=True,
    )
    pages = sorted(out_dir.glob("page-*.png"))
    print(f"[{name}] rasterized {len(pages)} pages")
    return pages


def build_batch_requests(pages: list[Path], doc_name: str) -> list[Request]:
    requests = []
    for page_path in pages:
        # pdftoppm names pages page-001.png, page-012.png — zero padded, sorts correctly.
        page_num = page_path.stem.split("-")[-1]
        image_b64 = base64.standard_b64encode(page_path.read_bytes()).decode("utf-8")
        requests.append(
            Request(
                custom_id=f"{doc_name}__{page_num}",
                params=MessageCreateParamsNonStreaming(
                    model=MODEL,
                    max_tokens=4096,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/png",
                                        "data": image_b64,
                                    },
                                },
                                {"type": "text", "text": PROMPT},
                            ],
                        }
                    ],
                ),
            )
        )
    return requests


def load_state() -> dict:
    if not STATE_FILE.exists():
        raise SystemExit(f"{STATE_FILE} not found — run `submit` first.")
    return json.loads(STATE_FILE.read_text())


def submit() -> None:
    client = anthropic.Anthropic()
    state = {}
    for doc in discover_docs():
        pages = rasterize(doc["pdf"], doc["name"])
        requests = build_batch_requests(pages, doc["name"])
        print(f"[{doc['name']}] submitting batch of {len(requests)} requests...")
        batch = client.messages.batches.create(requests=requests)
        print(f"[{doc['name']}] batch id: {batch.id} status: {batch.processing_status}")
        state[doc["name"]] = {"batch_id": batch.id, "page_count": len(pages)}
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))
    print(f"\nSaved batch state to {STATE_FILE}")


def poll() -> None:
    client = anthropic.Anthropic()
    state = load_state()
    pending = set(state.keys())
    while pending:
        for name in list(pending):
            batch = client.messages.batches.retrieve(state[name]["batch_id"])
            c = batch.request_counts
            print(
                f"[{time.strftime('%H:%M:%S')}] {name}: {batch.processing_status} "
                f"(succeeded={c.succeeded} errored={c.errored} processing={c.processing} "
                f"canceled={c.canceled} expired={c.expired})"
            )
            if batch.processing_status == "ended":
                pending.discard(name)
        if pending:
            time.sleep(POLL_INTERVAL)
    print("All batches ended.")


def collect() -> None:
    client = anthropic.Anthropic()
    state = load_state()
    HANDBOOKS_DIR.mkdir(parents=True, exist_ok=True)
    exit_code = 0
    for doc in discover_docs():
        name = doc["name"]
        if name not in state:
            print(f"[{name}] no batch recorded — skipping")
            continue
        pages_md: dict[int, str] = {}
        errors = []
        for result in client.messages.batches.results(state[name]["batch_id"]):
            page_num = int(result.custom_id.split("__")[-1])
            if result.result.type != "succeeded":
                errors.append((page_num, result.result.type))
                continue
            # The message comes back as a plain dict in some SDK versions.
            msg = result.result.message
            content = msg["content"] if isinstance(msg, dict) else msg.content
            text = ""
            for b in content:
                b_type = b["type"] if isinstance(b, dict) else b.type
                if b_type == "text":
                    text = b["text"] if isinstance(b, dict) else b.text
                    break
            pages_md[page_num] = text

        if errors:
            print(f"[{name}] {len(errors)} page(s) did not succeed: {sorted(errors)}")
            exit_code = 1

        out_lines = [f"# {doc['title']}\n"]
        for p in sorted(pages_md):
            out_lines += [f"\n<!-- page {p} -->\n", pages_md[p], "\n"]
        doc["output"].write_text("\n".join(out_lines))
        print(f"[{name}] wrote {doc['output']} ({len(pages_md)} pages, {len(errors)} errors)")

    sys.exit(exit_code)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    ap.add_argument("command", choices=["submit", "poll", "collect"])
    args = ap.parse_args()
    require_api_key()  # the SDK reads ANTHROPIC_API_KEY from the environment
    {"submit": submit, "poll": poll, "collect": collect}[args.command]()


if __name__ == "__main__":
    main()
