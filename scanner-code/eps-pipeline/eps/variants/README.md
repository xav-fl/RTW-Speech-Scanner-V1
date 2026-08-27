# Variant staging

`check_variant.py` runs the whole extract -> build path against a `FakeProvider`,
with no network and no API key:

```powershell
python variants\check_variant.py
```

It prints `PROMPT_VERSION`, `prompt_sha`, the size of the Stage 1 prompt, and
whether the Stage 2 prompt orders quotation before code list. It also holds two
guards: no residual code or title appears in any instruction text, and the
Stage 1 `reason` never reaches a Stage 2 prompt.

`A_change1_P4.py` is a snapshot of the P4 state (mechanism-first framing in
`_refine()`, no subcategories in `classify()`), kept because P4 is a measured
run in the history table. It is not a variant to run next.

## Run history

| Version | Change | Residual share | Canonical case | prompt_sha |
|---|---|---|---|---|
| P2 | baseline | 11/24 = 46% | I28 | — |
| P3 | residual codes named in prompt | 16/26 = 62% | I28 | — |
| P4 | mechanism-first framing in `_refine()` | 20/26 = 77% | I28 | `c27bb2b5fb15` |
| P5 | subcategories nested under majors in `classify()` | 9/16 = 56% | I28 | `36fa95c6ec3f` |
| P6 | level-2/3 primaries recovered instead of rejected | not yet run | — | `b6931002789d` |

P5's number is not comparable with the rest: three observations were rejected
outright for returning a level-2 code in the primary slot, so the denominator
lost rows for a parsing reason rather than a classification one. P6 fixes that
and holds every prompt string identical to P5, which is what makes it the run
that says what P5's structural change was actually worth.

## Cache note

`ResponseCache.key()` includes `prompt_version`, so bumping `PROMPT_VERSION`
invalidates Stage 1 passage selection as well as the classification calls. Each
run re-queries extraction and the observation set can shift between variants.
Compare shares, not counts.
