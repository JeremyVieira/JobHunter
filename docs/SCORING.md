# How scoring works

Every posting gets a **fit score** from 0 to 100, plus an explanation you can read in the
dashboard under "Why this score".

## 1. Weighted dimensions

Weights are relative (they are normalised by their sum) and live in `ScoringRulesConfig`.

| Dimension | Weight | What it measures |
| --- | --- | --- |
| Requirement coverage ("skills") | 30 | Share of the skills the posting asks for that you can truthfully claim. Required skills (and skills in the title) weigh 1.0, unmarked mentions 0.8, nice-to-haves 0.4. Few named skills shrink the score toward 50 instead of trusting thin evidence. |
| Title match | 24 | Match against your target roles; priority roles score above broader ones. |
| Experience | 14 | Years asked vs. your years, with one year of stretch. Silence scores a neutral 80, not the best case. |
| Montreal proximity | 8 | Local vs. elsewhere. |
| Salary, remote, education, commute | 4 / 3 / 3 / 2 | Weak signals that barely vary between postings, so they carry little weight. |

## 2. Adjustments

| Adjustment | Effect |
| --- | --- |
| Entry-level wording ("new grad", stated need of <=1 year) | + |
| Bilingual posting, for bilingual candidates | + |
| Fresh (<=3 days) / stale (>45 days) | + / - |
| Culture and established-employer signals | + |
| Hard-stack gaps (Java, C#, Kotlin... named prominently and absent from your skills) | - per gap, capped |
| Posting language you do not speak | - |
| Senior / staff / numbered levels, 7+ years, tiny-startup signals | - |
| Preference model (your applied vs. dismissed history) | at most +/- 8 |

Management and executive titles are removed before scoring (entry-level "Associate Product
Manager" programs are the exception).

## 3. Soft saturation

Above 88 points the excess is compressed (35%), so several excellent postings do not all clip to
100 and the top of the ranking stays ordered.

## 4. What the score is not

- **Match strength** in the dashboard is a heuristic blend of fit and skill coverage, not a callback
  probability. Your real response rates are in the Funnel, which only counts outcomes you record.
- The skill taxonomy is finite. A skill it does not know is invisible to coverage scoring unless you
  add it to `USER_KEYWORDS` (custom terms are matched as written).

## Tuning

Change weights in `jobhunter/config/settings.py` (`SCORING_RULES_DATA`) and hard filters in
`jobhunter/filter.py`. `python -m jobhunter demo` is a quick way to see the effect on a stable set
of synthetic postings.
