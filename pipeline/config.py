"""Shared paths and settings for the ingestion pipeline.

Everything is resolved relative to the repository root so the pipeline runs from
a clone with no editing. The data directory holds the source PDFs and every
generated artifact; it is deliberately kept out of version control (see
`.gitignore`) because the PWA and the reference handbooks are not ours to
redistribute.

Override the location with the `PWA_DATA_DIR` environment variable — useful when
the PDFs and extracted text live outside the checkout:

    PWA_DATA_DIR=~/documents/pwa python3 pipeline/extract_contract.py
"""

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(REPO_ROOT / ".env")

DATA_DIR = Path(os.environ.get("PWA_DATA_DIR", REPO_ROOT / "data")).expanduser().resolve()

# ── Inputs ────────────────────────────────────────────────────────────────────
ORIGINAL_DIR = DATA_DIR / "original"
PDF = ORIGINAL_DIR / "live-contract.pdf"

# ── Outputs ───────────────────────────────────────────────────────────────────
EXTRACTED_DIR = DATA_DIR / "extracted"
OUT_MD = EXTRACTED_DIR / "live-contract-full.md"
# Successful page transcriptions, keyed by page number, so a rerun only redoes
# what failed. Must be cleared when the PDF is replaced — a new edition is
# repaginated and stale entries would be reused silently against wrong pages.
OCR_CACHE = EXTRACTED_DIR / "ocr_cache"

# Navigation index for the `contract` skill, regenerated on every split. Lives
# with the data rather than in the repository: it is a listing of the ingested
# document's contents, so it belongs to whoever owns that document.
INDEX_MD = DATA_DIR / "INDEX.md"

SECTIONS_DIR = DATA_DIR / "sections"
LOA_DIR = DATA_DIR / "loa"
MOU_DIR = DATA_DIR / "mou"
HANDBOOKS_DIR = DATA_DIR / "handbooks"

# Rasterized page PNGs. Regenerable, so this is scratch space rather than output.
PAGE_IMG_DIR = DATA_DIR / "page_images"

# ── API ───────────────────────────────────────────────────────────────────────
API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MODEL = os.environ.get("PWA_MODEL", "claude-sonnet-5")


def require_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise SystemExit(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill it in, "
            "or export the variable."
        )
    return key


def require_pdf(path: Path) -> Path:
    if not path.exists():
        raise SystemExit(
            f"{path} not found.\n"
            f"Put the source PDF there (see README, 'Quick start'), or point "
            f"PWA_DATA_DIR at the directory that holds it."
        )
    return path
