# Aircraft, categories, and pay tiers

Pilot vocabulary and the rules for reasoning about it. The authoritative groupings and
rates are in the contract — look them up there every time rather than caching them here,
because both change with each edition.

## Category

A **category** = aircraft type + status (Captain / First Officer) + base. Defined in the
vacancies section (Section 22 A. 6 in the Delta PWA).

When a pilot says "I'm on the 320" or "I fly the 73N," they mean their **type**, not a
specific model.

## Type

A type is a single training qualification covering several models. A pilot qualified on a
type can be assigned **any model within it** on a given trip, and is paid at the rate of
the model actually flown.

The definitive list of types and the models in each is in the definitions section
(**Section 2 A. 14**, mirrored in Section 22 A. 3). Read it from
`data/sections/section_02_*.txt` to resolve a pilot's type before answering anything that
depends on it.

The same section also drives the **widebody / narrowbody** split, which matters for
scheduling rules, ALV limits, and reserve provisions.

## Shorthand

Pilot slang for types, which the contract itself does not use. Map these to the model
families, then resolve the family against Section 2 A. 14:

| Shorthand | Refers to |
|---|---|
| 777, 787 / Dreamliner, 767, 757, 717 | the Boeing model of that number |
| 73N / Boeing NB | the Boeing 737 family |
| 764 | the Boeing 767-400ER specifically |
| 7er | the Boeing 767/757 grouping |
| 350, 330, 320, 220 | the Airbus A-350 / A-330 / A-320 / A-220 families |
| Airbus NB | the Airbus narrowbody family (the "320" type) |
| ERJ | the Embraer family |
| CRJ | the Bombardier CRJ |

## Pay tiers

**Never assume two models in the same type pay the same rate.** They frequently do not —
some models sit a tier above their type-mates, and a family can be split across tiers. The
grouping is a *training* qualification, not a pay grade.

So for any pay question:

1. Resolve the pilot's type from Section 2 A. 14.
2. Pull the rate for **every model in that type** at their longevity year from the current
   pay table in the compensation section (Section 3 B. 2.d), Captain and First Officer as
   relevant.
3. Present them as a comparison, not a single number — the pilot can be assigned any of
   them.

Always read live values out of `data/sections/section_03_*.txt`. Rates change with each
contractual increase, and the pay tables are OCR'd from image-only pages, so quoting them
from memory risks being both stale and wrong.
