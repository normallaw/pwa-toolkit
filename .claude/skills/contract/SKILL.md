---
name: contract
description: Answer questions about the Delta Pilot Working Agreement (PWA) — contract provisions, LOAs, MOUs, pay rates, scheduling, bidding, work rules, reserve, leave, benefits, seniority, training. Use this for any question a Delta line pilot would ask about their working conditions, even when the user doesn't say "the contract".
---

# Delta PWA

Answer questions about the Delta Pilot Working Agreement by searching the extracted
contract text, not from general knowledge. Delta's specific rules govern.

Use this skill for the contract itself (sections, LOAs, MOUs) and for the working
conditions it defines: pay and guarantees, scheduling and bidding (PBS, rotations,
reserve, reroutes, green/white slips, premium and proffered flying, drafting), hours of
service and rest, deadheading, vacation, sick leave, leaves of absence, insurance and
retirement, seniority, furlough and recall, vacancies, training.

## Data sources

All paths are relative to the repository root. `$PWA_DATA_DIR` overrides `data/`.

| Path | What it is | Authority |
|---|---|---|
| `data/INDEX.md` | Generated index — every section, LOA and MOU with its title, page range and filename | Navigation |
| `data/sections/*.txt` | PWA sections + front matter | **Binding** |
| `data/loa/*.txt` | Letters of Agreement | **Binding** |
| `data/mou/*.txt` | Memoranda of Understanding | **Binding** |
| `data/handbooks/*.md` | MEC committee reference handbooks (PBS, Scheduling) | Explanatory only |

**Read `data/INDEX.md` first** to find the right document. It is regenerated on every
ingestion, so it always describes the edition actually sitting in `data/` — never assume a
section number or an LOA title from memory. If it is missing (ingested before the index
existed), `ls data/sections/ data/loa/ data/mou/` gives the same picture from the
filenames, and `python3 pipeline/split_contract.py` will rebuild it.

**Never read `data/original/*.pdf`.** They are the binaries the text was extracted from;
reading them yields unreliable results. `data/extracted/live-contract-full.md` is the
merged extraction with per-page provenance markers — useful for checking a page's source
(`text` vs `ocr`), not for searching.

If these directories are empty, the contract has not been ingested yet. Say so and point
the user at the pipeline (`README.md` → Quick start); do not answer from memory.

### Contract vs. handbooks

The PWA is authoritative and binding. The handbooks are MEC committee-authored
**explanatory guides** — good on day-to-day mechanics, but they paraphrase the contract
and may lag it.

- Cite the **PWA** for what a pilot is contractually entitled to.
- Cite a **handbook** for how a process works in practice (building a PBS bid, how a
  reroute is handled).
- With both in play, lead with the contract answer and use the handbook for mechanics.
  If they conflict, **the PWA controls** — say so.
- Name the handbook when citing it ("per the PBS Reference Handbook") so it is clear the
  source is explanatory, not contractual.

## Pilot profile

**Read `pilot_profile.md` first** (repo root; copy `pilot_profile.example.md` if absent).
Use the profile marked `active: true` to pre-compute and pre-fill:

- **Longevity year** — completed years since date of hire, as of today
- **Mandatory retirement date** — 65th birthday, if DOB is set
- **Category freeze expiration** — from date of last category change; freeze lengths by
  type are in Section 22 G
- **Aircraft type**, so pay questions need no follow-up
- **Base**, for category-specific questions
- **Former NWA pilot** — triggers NWA-specific provisions throughout the contract

If a needed field is `(not set)`, ask for it and suggest updating `pilot_profile.md`.

**Never assume line holder vs. reserve.** It changes bid period to bid period and is not
in the profile, and many provisions differ sharply between the two (rotation guarantees,
scheduling obligations, pay protections). When the answer turns on it, ask: *"Are you a
regular line holder or reserve this bid period?"*

## How to answer

Answers are usually read on a phone. Keep them short.

1. **Locate** the likely document(s) in `data/INDEX.md`, then **search** with grep across
   the text files:
   ```bash
   grep -rni "search term" data/sections/ data/loa/ data/mou/
   grep -rni -C 3 "search term" data/sections/          # with context
   grep -rEi "pattern" data/sections/ data/loa/ data/mou/ data/handbooks/
   ```
   For PBS or day-to-day scheduling mechanics, include `data/handbooks/`, weighted per the
   authority note above.
2. **Read** the surrounding provision for full context — do not answer off a grep line.
3. **Answer**:
   - Lead with the direct answer in 1–2 sentences.
   - Cite the provision (e.g. "Section 11 B. 1.", "LOA #23-02").
   - Quote only when the exact wording matters.
   - Skip long explanations unless asked.

### Pay rate questions

When a pilot asks their rate for an aircraft ("I fly the 320, what's my rate?"), show
**every model within their aircraft type**, not just the one named. A pilot can be
assigned any model within their type on a trip and is paid at the rate of the model
actually flown (Section 3 B. 2, note 3).

1. Compute the **longevity year** from date of hire.
2. Look up the **type grouping** in Section 2 A. 14.
3. Pull the rate for **every model in that type** at that longevity year from the current
   pay table in Section 3 B. 2.d, Captain and First Officer as relevant.
4. Present as a short comparison list.

See `references/aircraft.md` — models within a type do not all pay the same, so a single
rate is usually the wrong answer.

## References

- `data/INDEX.md` — generated: sections, LOAs, MOUs, page ranges, filenames
- `references/aircraft.md` — categories, pilot shorthand for aircraft types, pay tier rules
