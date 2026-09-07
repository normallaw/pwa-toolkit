# How the extraction works

The PWA is a ~600-page PDF. A naive approach — OCR every page — is slow, expensive, and
strictly worse than what the file already contains: most of its pages carry a clean
embedded text layer with the original layout and left-margin line numbers intact. The
pipeline's job is to work out which pages those are, take them verbatim, and spend model
calls only on the pages that genuinely need them.

On the February 2026 edition, 617 pages break down as:

| Pages | Source | Why |
|------:|---|---|
| 520 | `pdftotext -layout`, verbatim | Sound text layer |
| 97 | Claude vision | 54 image-only, 43 fully scrambled |

That is ~16% of pages sent to the model, and a run takes minutes.

## Page classification

`classify()` in `pipeline/extract_contract.py` sorts every page into one of three buckets
using only its extracted text — no page images, no API calls, so `--dry-run` gives you the
whole cost estimate for free:

- **sparse** — fewer than 400 non-whitespace characters. These are images with no text
  layer: the Section 3 composite pay tables, appendix pages, signature pages.
- **scrambled** — the page unshifts into far more common English words than it currently
  contains (`dec_hits > raw_hits * 2`). Explained below.
- **clean** — everything else. Lifted verbatim.

## The custom font encoding

Some LOA and MOU pages are set in a font with a custom encoding. `pdftotext` faithfully
reports the code points, which come out as mojibake: `LOA` extracts as `/2$`.

The encoding is a uniform shift. Every character sits **29 below** its true value, and the
space is written as `\x03` — so `\x06` is `#` and `\x14` is `1`. That makes it *decodable*
rather than lost, which is strictly better than OCR: you recover the original text instead
of a transcription of it.

The catch is that decoding cannot be applied blindly, because ordinary text occupies the
same character range. The word `UNDERSTANDING`, the year `2026`, the margin line numbers,
and the rest-facility code `4A/2D` all unshift into plausible-looking nonsense (`4A/2D`
becomes `Q^LOa`, which would otherwise match on the seed word `loa`).

So `decode_mojibake()` decides **per token**, and only decodes when unshifting reveals a
word this document actually uses. The vocabulary is learned from the document's own clean
pages — any word appearing five or more times, plus a small seed set of short
document-specific terms (`loa`, `mou`, `pwa`, `alpa`, ...) that a frequency filter would
miss. The result must also contain no implausible symbols.

Tokens too short to judge on their own inherit the previous token's decision. That is what
turns `([KLELW $` into `Exhibit A` rather than `Exhibit $`.

This handles **mixed** pages — where only the running header and a caption are encoded
while the body extracts perfectly — which keep their exact text layer instead of being
sent to OCR. **Fully** scrambled pages still go to the model: with no clean text anywhere
on the page, too many short function words (`and`, `the`, `as`) fall below the vocabulary
threshold to decode the page reliably.

## Vision transcription

Pages that need it are rasterized at 200 DPI and sent to `claude-sonnet-5` with a prompt
that emphasizes exact table transcription — the pay tables are the highest-stakes data in
the contract and they are image-only, so every cell value matters.

Two things keep reruns cheap:

- **Per-page caching.** Successful transcriptions land in `data/extracted/ocr_cache/`,
  keyed by page number. A rerun after a partial failure only redoes what failed. This is
  also why the cache **must** be cleared when the PDF is replaced — a new edition is
  repaginated, and stale entries would be reused silently against the wrong pages.
- **Retries with backoff.** Five attempts, exponential. Anything that still fails is
  marked `<!-- OCR FAILED ... -->` in the output and the script exits non-zero, so a
  failure is loud rather than a silent hole in the contract.

Eight requests run concurrently by default (`--workers`).

## Merging and splitting

`extract_contract.py` writes one file, `data/extracted/live-contract-full.md`, with a
provenance marker above every page:

```
<!-- page 412 | ocr -->
```

`split_contract.py` reads those markers and cuts the file into per-document files. It
identifies documents from the **running page header** at the top of each page
(`Section 23 - Scheduling`, `LOA #23-02 - Global Scope`) and forward-fills pages that have
none — tab dividers, signature pages, full-page tables.

Titles come from the **table of contents**, not the headers, because the TOC is the only
place that names every document consistently. Running headers are sometimes truncated
(LOA #13-05) and sometimes title-less, carrying only a bare number (MOU #25-01). Because
the TOC also names every document, pages before the Section 1 tab divider are excluded
from identification, or they would each match as a document start.

Both of those inputs are derived from the document itself, which is the point: the
splitter re-derives correctly on the next edition rather than needing hand-maintained line
number anchors.

## Verifying an extraction

Two checks catch essentially everything that can go wrong:

1. **The contract's own inventory.** Section 29 C. lists every LOA and MOU that survives
   the PWA. The extracted file set must match it exactly. This is the best available check
   that no document was missed or absorbed into a neighbour.
2. **The pay tables, cell for cell.** They come entirely from OCR and they are what people
   will actually rely on. Re-rasterize the pages and compare against the extracted tables
   by eye.

Plus the cheap one: `grep -rl "OCR FAILED" data/sections data/loa data/mou` must print
nothing.

## The handbooks are a different problem

The MEC reference handbooks have no usable text layer at all — much of their content is
text baked into screenshots of the bidding and scheduling software. Every page needs
vision, so `pipeline/transcribe_handbooks.py` uses the **Message Batches API** instead:
asynchronous, half price, and nobody is waiting on the result. Submit, poll, collect.

## Prior art in this repo's history

An earlier version of this pipeline ran [marker-pdf](https://github.com/VikParuchuri/marker)
locally, OCR'ing every page. On CPU it took roughly 17 hours for the full contract, and
its output had to be split by hand-maintained line-number anchors that did not survive a
re-extraction. The current pipeline replaced it: minutes instead of hours, verbatim text
where the PDF supplies it, and a splitter that re-derives itself from the document.
