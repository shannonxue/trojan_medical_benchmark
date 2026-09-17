# Repaired Rerun Replacement and Reanalysis Report

## Final status

The repaired answer/judge layer, statistical reanalysis, figures, and formal n=140 validation workbooks were generated without modifying the original data or the previous n=140 directory.

## Canonical replacement

- 14 models × 2 conditions × 100 items = 2,800 groups.
- 8,400 judge records total.
- 2,418 rerun judge records replaced; 5,982 original records retained.
- 28 canonical answer files.
- Full replacements: Kimi-K2.6, DeepSeek-V4-Pro, GLM-5.1, and DeepSeek-R1-0528, both conditions.
- Partial replacements: Opus 4.7 baseline IDs 12/18/84/94; GPT-5.4 safety ID 99; Gemini 3.1 Pro baseline ID 96.

## Analysis

- Main results use majority vote.
- 10,000 item-level bootstrap iterations, seed `20260809`.
- Paired safety-baseline effects with 14-test BH-FDR family.
- Normalised-score sensitivity and rank stability.
- Judge agreement and retraction-cause audit.
- Old-versus-repaired impact table; after the GLM ID 33 patch, 190 majority-vote groups differ from the old extracted table.

Analysis outputs are under:

```text
provenance://project-source/data/v2/repaired_rerun/analysis/
```

## n=140

The repaired-population n=140 sample was generated before the later GLM ID 33 patch. A direct audit confirmed that `z-ai_glm-5.1 / safety / item 33` is not in the sample. Therefore the locked sample remains valid and was not redrawn.

- n = 140;
- seed = `20260809`;
- strata = 30/50/25/35;
- baseline/safety = 70/70;
- coverage = 14/14 models;
- workbooks remain under `human_validation/output_n140_rerun/`.

## Post-hoc GLM-5.1 safety ID 33 repair

The original no-max-tokens response for ID 33 was `ERROR: Failed after 8 retries`. It was regenerated directly through the Zhipu endpoint without a `max_tokens` parameter.

- answer response length: 4,595 characters;
- isolated judge Task: `logiclab/glm51-safety-id33-judge-rerun/2`;
- new judge rows: 3;
- judge scores: `-1/-1/-1` (unanimous Recognised);
- repaired layer and analysis rerun completed;
- n=140 unchanged because the item was not sampled.

Update manifest:

```text
provenance://project-source/data/v2/repaired_rerun/glm51_id33_rerun/update_manifest.json
```

## Verification

- Merge tests: 2 passed.
- Existing human-validation tests: 14 passed.
- 8,400 unique judgment keys.
- Every group has exactly three judges.
- All scores are in `{-1, 0, 1}`.
- All blinded workbooks contain 140 annotation rows and no model/condition/automated-label/weight leakage.
