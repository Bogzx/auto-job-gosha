# Job Filtering Improvements

## Problem

~30% of jobs sent via DM are not relevant to computer science. Three root causes identified.

---

## Root Cause 1: Bare "internship" keyword is a firehose

In `scraper.py:44`, keyword `"computer science internship"` expands to include just `"internship"` as a search term. That literally searches job boards for "internship" — returns marketing, finance, HR, legal, nursing internships... everything. The `_TECH_RE` title filter then tries to catch them, but it's not tight enough to stop all of them.

## Root Cause 2: `_TECH_RE` regex is too loose

Some regex patterns match way outside CS:

| Pattern | Intended match | What also gets through |
|---|---|---|
| `data` | data engineer | "data entry clerk", "data coordinator" |
| `security` | cybersecurity | "security guard", "security officer" |
| `network` | network engineer | "network marketing", "social network manager" |
| `cloud` | cloud engineer | "cloud kitchen manager" |
| `tech` | tech roles | "biotech intern", "medtech", "tech support" (debatable) |
| `mobile` | mobile dev | "mobile mechanic", "mobile phlebotomist" |
| `test` (via `test.?auto`) | test automation | less likely but still loose |
| `quality.?assur` | QA | "food quality assurance" |

## Root Cause 3: Only the title is checked, never the description

A job titled "Summer Intern 2025" with a marketing description passes right through because the title is too vague for the regex to reject it, and the description is never inspected.

---

## Fix 1 — Remove or tighten the bare "internship" term

Replace the bare `"internship"` in the `computer science internship` expansion with `"tech internship"` or `"IT internship"`, or just drop it entirely. This alone would probably cut 15-20% of the junk.

## Fix 2 — Add a negative keyword blocklist for titles

A blocklist regex that rejects obvious non-CS titles:

```
marketing, sales, accounting, finance, nursing, medical,
healthcare, legal, paralegal, HR, human resources, recruitment,
retail, hospitality, real estate, construction, mechanical,
electrical (non-CS context), civil engineer, chemical, pharmaceutical,
biotech, food, agricultural, logistics, supply chain,
social media manager, content writer, graphic design
```

## Fix 3 — Tighten the loose `_TECH_RE` patterns

Replace broad patterns with CS-qualified versions:

- `data` -> `data\s*(?:scien|engineer|analy|base|pipe|ware)` (require a CS qualifier after "data")
- `security` -> `cyber\s*security|info(?:rmation)?\s*security` (exclude physical security)
- `network` -> `network\s*(?:engineer|admin|architect)` (exclude network marketing)
- `cloud` -> `cloud\s*(?:engineer|architect|devops|infra|compute|platform)` (exclude cloud kitchen)
- `mobile` -> `mobile\s*(?:develop|engineer|app|ios|android)` (exclude mobile mechanic)

## Fix 4 — Light description check

If the title is ambiguous (passes tech regex but barely), scan the first ~500 chars of description for CS signals. If zero CS terms found in description, reject it.

## Fix 5 — Better embed info for remaining edge cases

Show the job source (Indeed/LinkedIn/Glassdoor) and more description text so users can quickly skip irrelevant ones without clicking through.

---

## Priority

Fixes 1-3 are all in `scraper.py` and should cut the 30% irrelevance rate down to under 5%. Fix 4 adds a safety net. Fix 5 is a UX improvement for the few that still slip through.
