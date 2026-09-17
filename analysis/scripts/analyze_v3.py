#!/usr/bin/env python3
"""Reanalyse the V3 repaired benchmark and completed n=140 human review.

All inputs are read-only. New outputs are written below analysis/.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import math
import platform
import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.stats import (
    mannwhitneyu,
    spearmanr,
    ttest_rel,
    wilcoxon,
)

try:
    import statsmodels.formula.api as smf
except Exception:  # pragma: no cover - analysis reports the missing dependency
    smf = None

SCRIPT_PATH = Path(__file__).resolve()
BUNDLE_ROOT = SCRIPT_PATH.parents[2]
IS_RELEASE_BUNDLE = (
    SCRIPT_PATH.parents[1].name == "analysis"
    and (BUNDLE_ROOT / "data/judgments_repaired.csv").exists()
)
IS_WORKING_COPY = (
    SCRIPT_PATH.parents[1].name == "reanalysis_v3"
    and (BUNDLE_ROOT / "data/repaired_rerun/judgments/judgment_records_repaired.csv").exists()
)
if IS_RELEASE_BUNDLE:
    PROJECT = BUNDLE_ROOT
    V3 = BUNDLE_ROOT
    OUT = BUNDLE_ROOT / "analysis"
elif IS_WORKING_COPY:
    PROJECT = BUNDLE_ROOT
    V3 = BUNDLE_ROOT
    OUT = SCRIPT_PATH.parents[1]
else:
    PROJECT = SCRIPT_PATH.parents[3]
    V3 = PROJECT / "V3"
    OUT = V3 / "reanalysis_v3"
INPUT = OUT / "inputs"
TABLES = OUT / "tables"
FIGURES = OUT / "figures"
HUMAN_OUT = OUT / "human_validation"
TEXT = OUT / "text_fragments"
TEMPLATES = OUT / "templates"
if IS_RELEASE_BUNDLE:
    JUDGMENTS_PATH = V3 / "data/judgments_repaired.csv"
    MASTER_PATH = V3 / "human_validation/n140_master_unblinded_postpatch_v3.xlsx"
    RATER_A_PATH = V3 / "human_validation/n140_rater_A_blinded.xlsx"
    RATER_B_PATH = V3 / "human_validation/n140_rater_B_blinded.xlsx"
    ADJUDICATION_PATH = V3 / "human_validation/adjudication_summary_13_rows.xlsx"
    METADATA_PATH = OUT / "inputs/retractions_selected_100.csv"
    CAUSE_AUDIT_PATH = OUT / "inputs/retraction_cause_audit_source.csv"
else:
    JUDGMENTS_PATH = V3 / "data/repaired_rerun/judgments/judgment_records_repaired.csv"
    MASTER_PATH = V3 / "human_validation/output_n140/n140_master_unblinded.xlsx"
    RATER_A_PATH = V3 / "human_blind/n140_rater_A_blinded.xlsx"
    RATER_B_PATH = V3 / "human_blind/n140_rater_B_blinded.xlsx"
    ADJUDICATION_PATH = V3 / "human_blind/human_label不一致清单汇总.xlsx"
    METADATA_PATH = (
        OUT / "inputs/retractions_selected_100.csv"
        if IS_WORKING_COPY
        else PROJECT / "provenance://project-source/data/v2/trojan sensitivity dataset/dataset/retractions.csv"
    )
    CAUSE_AUDIT_PATH = V3 / "data/repaired_rerun/analysis/retraction_cause_audit_repaired.csv"
CAUSE_OVERRIDE_PATH = OUT / "inputs/retraction_cause_overrides_v3.csv"
SEED = 20260809
BOOTSTRAP = 10_000
ANALYSIS_DATE = pd.Timestamp("2026-09-01")
# Supplementary Tables 1--16 are assembled by write_supplementary(); the test suite
# asserts the same count, so the manifest verification flag reads from one constant.
EXPECTED_SUPPLEMENTARY_TABLES = 16
LABELS = ["Polluted", "Neutral", "Recognised"]
# Value sets permitted by the frozen human reviewer guidelines (human_validation/
# human_reviewer_guidelines.md, section 6).  Values that were permitted but never chosen are
# retained with a zero count so that a null result remains visible in the reported tables.
PERMITTED_SECONDARY_VALUES = {
    "conclusion_overlap": ["Yes", "No", "Unclear", "Not applicable"],
    "neutral_subtype": [
        "Valid alternative evidence",
        "Appropriate avoidance/abstention",
        "No substantive evidence",
        "Unverifiable/fabricated citation",
        "Other retracted evidence",
        "Unclear",
        "Not applicable",
    ],
    "republication_handling": ["Correct", "Incorrect", "Not mentioned", "Unclear", "Not applicable"],
    "confidence": ["High", "Moderate", "Low"],
}
# Annotators may route a case to adjudication with `Unclear`; it is never a final label.
RATER_LABELS = [*LABELS, "Unclear"]
JUDGE_ORDER = ["gpt55", "opus47", "gemini31pro"]
SENSITIVITY_SCHEMES = {
    "default": {"Polluted": 1.0, "Neutral": 0.0, "Recognised": -1.0},
    "pollution_avoidance": {"Polluted": 1.0, "Neutral": 0.0, "Recognised": 0.0},
    "polluted_2x": {"Polluted": 2.0, "Neutral": 0.0, "Recognised": -1.0},
    "neutral_0.25": {"Polluted": 1.0, "Neutral": 0.25, "Recognised": -1.0},
    "neutral_0.50": {"Polluted": 1.0, "Neutral": 0.50, "Recognised": -1.0},
    "neutral_0.75": {"Polluted": 1.0, "Neutral": 0.75, "Recognised": -1.0},
}


def ensure_dirs() -> None:
    for d in [OUT, INPUT, TABLES, FIGURES, HUMAN_OUT, TEXT, OUT / "scripts", OUT / "tests"]:
        d.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, obj: object) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_input_manifest() -> None:
    input_paths = [
        JUDGMENTS_PATH,
        MASTER_PATH,
        RATER_A_PATH,
        RATER_B_PATH,
        # The adjudicator's returned workbook is deliberately absent: it is not read by this
        # analysis and is excluded from the released materials.  The adjudicated labels and reasons
        # enter through ADJUDICATION_PATH.
        ADJUDICATION_PATH,
        METADATA_PATH,
        CAUSE_AUDIT_PATH,
        CAUSE_OVERRIDE_PATH,
    ]
    packages = ["numpy", "pandas", "scipy", "statsmodels", "openpyxl", "matplotlib"]
    versions = {"python": platform.python_version()}
    for package in packages:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "not-installed"
    manifest_role = "portable_release_inputs" if IS_RELEASE_BUNDLE else "current_working_copy_inputs"
    path_base = "release_candidate" if IS_RELEASE_BUNDLE else "repository_root"
    historical_status = (
        "Current portable paths; prior legacy source-location labels are historical only and are not active inputs."
        if IS_RELEASE_BUNDLE
        else "Supersedes prior manifests whose provenance://v3-source/... paths were historical location labels; input identity is controlled by bytes and SHA-256."
    )
    historical_path = (
        "analysis/input_manifest_v3_historical.json"
        if IS_RELEASE_BUNDLE
        else "reanalysis_v3/input_manifest_v3_historical.json"
    )
    write_json(OUT / "input_manifest_v3.json", {
        "manifest_role": manifest_role,
        "path_base": path_base,
        "historical_record_status": historical_status,
        "historical_record_path": historical_path,
        "analysis_seed": SEED,
        "bootstrap_iterations": BOOTSTRAP,
        "analysis_date": str(ANALYSIS_DATE.date()),
        "inputs": [
            {
                "path": str(path.relative_to(PROJECT)),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in input_paths
        ],
        "software_versions": versions,
    })


def assemble_supplement(generated_tables: str) -> str:
    """Join generated Tables 1--12 to the reviewed fixed supplement sections."""
    front = (TEMPLATES / "supplement_frontmatter.tex").read_text(encoding="utf-8").rstrip()
    tail = (TEMPLATES / "supplement_tail_tables_13_17.tex").read_text(encoding="utf-8").rstrip()
    return f"{front}\n{generated_tables.rstrip()}\n{tail}\n\\end{{document}}\n"


def bh_qvalues(p_values: Iterable[float]) -> np.ndarray:
    p = np.asarray(list(p_values), dtype=float)
    q = np.full(len(p), np.nan, dtype=float)
    valid = np.isfinite(p)
    if not valid.any():
        return q
    pv = p[valid]
    order = np.argsort(pv)
    running = 1.0
    out = np.empty(len(pv), dtype=float)
    for rank, idx in reversed(list(enumerate(order, 1))):
        running = min(running, pv[idx] * len(pv) / rank)
        out[idx] = running
    q[valid] = out
    return q


def score_summary(scores: np.ndarray) -> dict[str, float | int]:
    scores = np.asarray(scores, dtype=float)
    n = len(scores)
    poll = int(np.sum(scores == 1))
    neutral = int(np.sum(scores == 0))
    recognised = int(np.sum(scores == -1))
    mean = float(np.mean(scores)) if n else np.nan
    return {
        "n": n,
        "polluted": poll,
        "neutral": neutral,
        "recognised": recognised,
        "polluted_rate": poll / n if n else np.nan,
        "neutral_rate": neutral / n if n else np.nan,
        "recognised_rate": recognised / n if n else np.nan,
        "normalised_score": 50 * (1 - mean) if n else np.nan,
        "antipollution_rate": recognised / (recognised + poll) if (recognised + poll) else np.nan,
    }


def pct_ci(values: np.ndarray) -> tuple[float, float]:
    return float(np.quantile(values, 0.025)), float(np.quantile(values, 0.975))


def wilson_ci(successes: int, trials: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """Two-sided 95% Wilson score interval for a binomial proportion."""
    if trials <= 0 or not 0 <= successes <= trials:
        raise ValueError("Wilson interval requires 0 <= successes <= trials and trials > 0")
    proportion = successes / trials
    denominator = 1 + z**2 / trials
    centre = (proportion + z**2 / (2 * trials)) / denominator
    half_width = z * math.sqrt(
        proportion * (1 - proportion) / trials + z**2 / (4 * trials**2)
    ) / denominator
    lower = 0.0 if successes == 0 else max(0.0, centre - half_width)
    upper = 1.0 if successes == trials else min(1.0, centre + half_width)
    return lower, upper


def item_bootstrap(scores: np.ndarray, rng: np.random.Generator) -> dict[str, float]:
    scores = np.asarray(scores, dtype=float)
    n = len(scores)
    idx = rng.integers(0, n, size=(BOOTSTRAP, n))
    sample = scores[idx]
    reduction_axes = tuple(range(1, sample.ndim))
    poll = (sample == 1).mean(axis=reduction_axes)
    neutral = (sample == 0).mean(axis=reduction_axes)
    rec = (sample == -1).mean(axis=reduction_axes)
    norm = 50 * (1 - sample.mean(axis=reduction_axes))
    return {
        "polluted_ci_low": pct_ci(poll)[0], "polluted_ci_high": pct_ci(poll)[1],
        "neutral_ci_low": pct_ci(neutral)[0], "neutral_ci_high": pct_ci(neutral)[1],
        "recognised_ci_low": pct_ci(rec)[0], "recognised_ci_high": pct_ci(rec)[1],
        "normalised_ci_low": pct_ci(norm)[0], "normalised_ci_high": pct_ci(norm)[1],
    }


def paired_item_bootstrap(base: np.ndarray, safe: np.ndarray, rng: np.random.Generator) -> dict[str, float]:
    n = len(base)
    idx = rng.integers(0, n, size=(BOOTSTRAP, n))
    b = base[idx]
    s = safe[idx]
    reduction_axes = tuple(range(1, b.ndim))
    delta_norm = 50 * (b.mean(axis=reduction_axes) - s.mean(axis=reduction_axes))
    delta_poll = (s == 1).mean(axis=reduction_axes) - (b == 1).mean(axis=reduction_axes)
    delta_rec = (s == -1).mean(axis=reduction_axes) - (b == -1).mean(axis=reduction_axes)
    return {
        "delta_norm_ci_low": pct_ci(delta_norm)[0], "delta_norm_ci_high": pct_ci(delta_norm)[1],
        "delta_poll_ci_low": pct_ci(delta_poll)[0], "delta_poll_ci_high": pct_ci(delta_poll)[1],
        "delta_rec_ci_low": pct_ci(delta_rec)[0], "delta_rec_ci_high": pct_ci(delta_rec)[1],
    }


def two_way_bootstrap(base: np.ndarray, safe: np.ndarray, rng: np.random.Generator) -> dict[str, float]:
    """Resample both fixed comparison models and items for a sensitivity CI."""
    n_items, n_models = base.shape
    dn, dp = [], []
    for _ in range(BOOTSTRAP):
        ii = rng.integers(0, n_items, n_items)
        mi = rng.integers(0, n_models, n_models)
        b = base[np.ix_(ii, mi)]
        s = safe[np.ix_(ii, mi)]
        dn.append(50 * (b.mean() - s.mean()))
        dp.append((s == 1).mean() - (b == 1).mean())
    return {
        "two_way_delta_norm_ci_low": float(np.quantile(dn, 0.025)),
        "two_way_delta_norm_ci_high": float(np.quantile(dn, 0.975)),
        "two_way_delta_poll_ci_low": float(np.quantile(dp, 0.025)),
        "two_way_delta_poll_ci_high": float(np.quantile(dp, 0.975)),
    }


def cohen_kappa(a: Iterable[str], b: Iterable[str]) -> float:
    a, b = list(a), list(b)
    n = len(a)
    if not n:
        return float("nan")
    p_o = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    p_e = sum(ca[k] / n * cb[k] / n for k in set(ca) | set(cb))
    return (p_o - p_e) / (1 - p_e) if p_e < 1 else float("nan")


def paired_kappa_bootstrap(a: Iterable[str], b: Iterable[str], rng: np.random.Generator) -> tuple[float, float]:
    """Percentile CI for raw A/B kappa, resampling paired annotations."""
    a = np.asarray(list(a), dtype=object)
    b = np.asarray(list(b), dtype=object)
    n = len(a)
    values = []
    for _ in range(BOOTSTRAP):
        idx = rng.integers(0, n, n)
        values.append(cohen_kappa(a[idx], b[idx]))
    finite = np.asarray([value for value in values if np.isfinite(value)], dtype=float)
    return pct_ci(finite)


def weighted_distribution(df: pd.DataFrame, label_col: str, weight_col: str = "design_weight") -> dict[str, float]:
    denom = float(df[weight_col].sum())
    return {label: float(df.loc[df[label_col] == label, weight_col].sum() / denom) for label in LABELS}


def read_xlsx_rows(path: Path, sheet: str = "annotations", max_row: int = 200) -> pd.DataFrame:
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet]
    rows = []
    for row in ws.iter_rows(min_row=1, max_row=max_row, values_only=True):
        if any(v is not None for v in row):
            rows.append(row)
    if not rows:
        raise ValueError(f"no rows in {path}:{sheet}")
    return pd.DataFrame(rows[1:], columns=rows[0])


LOCKED_THEME_GROUPS = {
    "Autoimmune & inflammatory": (2, 23),
    "Cardiovascular & hypertension": (21, 24, 34, 45, 54, 62, 67, 72, 73, 85, 96),
    "Critical care & infection": (28,),
    "Depression & psychiatric": (20,),
    "Diabetes & metabolic": (32, 41, 79, 81, 88),
    "Gastrointestinal": (40, 95),
    "Musculoskeletal & fracture": (29, 30, 31, 50, 61, 65, 70, 89),
    "Neurology": (86,),
    "Other": (3, 4, 5, 11, 33, 37, 42, 51, 63, 64, 68, 69, 71, 76, 77, 87, 90),
    "PCOS & ovulation induction": (15, 16, 80, 91, 93, 94, 99),
    "PONV & perioperative antiemetics": (43, 44, 46, 47, 49, 78, 82),
    "Perioperative pain & anesthesia": (19, 36, 48, 55, 56, 58, 66, 83, 84, 98),
    "Pregnancy & reproductive": (6, 10, 74, 75, 92, 100),
    "Vitamin D supplementation": (7, 8, 9, 22, 25, 26, 27),
    "Volume therapy & colloids": (1, 12, 13, 14, 17, 18, 35, 38, 39, 52, 53, 57, 59, 60, 97),
}
LOCKED_THEME_BY_ITEM = {
    item_id: theme
    for theme, item_ids in LOCKED_THEME_GROUPS.items()
    for item_id in item_ids
}
if len(LOCKED_THEME_BY_ITEM) != 100 or set(LOCKED_THEME_BY_ITEM) != set(range(1, 101)):
    raise RuntimeError("locked theme mapping must contain every item ID 1--100 exactly once")


def load_benchmark() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    path = JUDGMENTS_PATH
    df = pd.read_csv(path)
    required = {"model", "condition", "item_id", "judge", "score", "label", "study_title", "retraction_context", "response_text"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"judgment input missing columns: {sorted(missing)}")
    df["item_id"] = df["item_id"].astype(int)
    df["score"] = df["score"].astype(int)
    if len(df) != 8400 or set(df["score"].unique()) != {-1, 0, 1}:
        raise ValueError(f"unexpected judgment shape/scores: {df.shape}, {df['score'].unique()}")
    if df.duplicated(["model", "condition", "item_id", "judge"]).any():
        raise ValueError("duplicate judgment key")
    rows = []
    for key, g in df.groupby(["model", "condition", "item_id"], sort=True):
        scores = dict(zip(g["judge"], g["score"]))
        if set(scores) != set(JUDGE_ORDER) or len(g) != 3:
            raise ValueError(f"invalid judge group {key}: {sorted(scores)}")
        vals = [int(scores[j]) for j in JUDGE_ORDER]
        counts = Counter(vals)
        top = [score for score, count in counts.items() if count == max(counts.values())]
        if len(top) != 1:
            raise ValueError(f"three-way majority tie: {key} {vals}")
        label = {-1: "Recognised", 0: "Neutral", 1: "Polluted"}[top[0]]
        r = {"model": key[0], "condition": key[1], "item_id": key[2],
             "judge_1_score": vals[0], "judge_2_score": vals[1], "judge_3_score": vals[2],
             "majority_score": int(top[0]), "majority_label": label,
             "stratum": "unanimous" if len(set(vals)) == 1 else "any_disagreement",
             "question_input": g.iloc[0]["question_input"], "study_title": g.iloc[0]["study_title"],
             "study_authors": g.iloc[0].get("study_authors", ""), "study_doi": g.iloc[0].get("study_doi", ""),
             "study_journal": g.iloc[0].get("study_journal", ""), "publication_date": g.iloc[0].get("publication_date", ""),
             "retraction_date": g.iloc[0].get("retraction_date", ""), "republished_status": g.iloc[0].get("republished_status", ""),
             "target_claim": g.iloc[0]["target_claim"], "retraction_context": g.iloc[0]["retraction_context"],
             "is_rerun": str(g.iloc[0].get("is_rerun", "False")).lower() == "true"}
        rows.append(r)
    majority = pd.DataFrame(rows)
    majority.to_csv(TABLES / "majority_votes_v3.csv", index=False)
    # Preserve judge-level scores without the very large response text column.
    cols = [c for c in df.columns if c != "response_text"]
    df[cols].to_csv(TABLES / "judge_scores_v3.csv", index=False)
    report = {"judge_rows": len(df), "groups": len(majority), "models": sorted(majority.model.unique()), "model_count": majority.model.nunique(), "conditions": sorted(majority.condition.unique()), "bootstrap_iterations": BOOTSTRAP, "seed": SEED}
    write_json(OUT / "benchmark_inventory.json", report)
    return df, majority, report


def load_item_metadata(majority: pd.DataFrame) -> pd.DataFrame:
    src = METADATA_PATH
    dst = INPUT / "retractions_selected_100.csv"
    if src.resolve() != dst.resolve():
        shutil.copy2(src, dst)
    raw = src.read_bytes()
    text = raw.decode("cp1252")
    rows = list(csv.DictReader(text.splitlines()))
    meta = pd.DataFrame(rows)
    if len(meta) != 100:
        raise ValueError(f"expected 100 selected metadata rows, got {len(meta)}")
    meta.insert(0, "item_id", np.arange(1, 101))
    meta["citations"] = pd.to_numeric(meta["Citations"], errors="coerce")
    meta["retraction_date_meta"] = pd.to_datetime(meta["RetractionDate"], errors="coerce")
    meta["publication_date_meta"] = pd.to_datetime(meta["Date of Publish"], errors="coerce")
    meta["theme"] = meta["item_id"].map(LOCKED_THEME_BY_ITEM)
    if meta["theme"].isna().any():
        raise ValueError("locked theme mapping does not cover all metadata item IDs")
    meta["theme_assignment_method"] = "locked 100-item mapping"
    titles = majority[["item_id", "study_title"]].drop_duplicates()
    meta = meta.merge(titles, on="item_id", how="left")
    norm = lambda x: " ".join(str(x).lower().replace("’", "'").split())
    meta["title_matches_judgment"] = [norm(a) == norm(b) for a, b in zip(meta["Title_New"], meta["study_title"])]
    meta.to_csv(TABLES / "item_metadata_v3.csv", index=False)
    if not bool(meta["title_matches_judgment"].all()):
        meta.loc[~meta["title_matches_judgment"]].to_csv(TABLES / "item_metadata_title_mismatches.csv", index=False)
    return meta


def make_summary_tables(majority: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(SEED)
    rows = []
    for (model, condition), g in majority.groupby(["model", "condition"], sort=True):
        point = score_summary(g["majority_score"].to_numpy())
        intervals = item_bootstrap(g["majority_score"].to_numpy(), rng)
        intervals["polluted_ci_low"], intervals["polluted_ci_high"] = wilson_ci(point["polluted"], point["n"])
        intervals["recognised_ci_low"], intervals["recognised_ci_high"] = wilson_ci(point["recognised"], point["n"])
        rows.append({"model": model, "condition": condition, **point, **intervals, "proportion_ci_method": "two-sided Wilson", "rerun_groups": int(g["is_rerun"].sum())})
    summary = pd.DataFrame(rows)
    summary.to_csv(TABLES / "summary_by_model_condition_v3.csv", index=False)
    baseline = summary[summary.condition == "baseline"].copy().sort_values(["normalised_score", "polluted_rate"], ascending=[False, True])
    baseline.insert(0, "rank", np.arange(1, len(baseline) + 1))
    baseline.to_csv(TABLES / "baseline_results_v3.csv", index=False)
    return summary, baseline


def make_prompt_effects(majority: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(SEED + 1)
    effects = []
    for model in sorted(majority.model.unique()):
        b = majority[(majority.model == model) & (majority.condition == "baseline")].set_index("item_id")["majority_score"]
        s = majority[(majority.model == model) & (majority.condition == "safety")].set_index("item_id")["majority_score"]
        ids = sorted(set(b.index) & set(s.index))
        base, safe = b.loc[ids].to_numpy(float), s.loc[ids].to_numpy(float)
        try:
            wilcoxon_result = wilcoxon(base - safe) if np.any(base != safe) else None
            w = float(wilcoxon_result.statistic) if wilcoxon_result is not None else 0.0
            p = float(wilcoxon_result.pvalue) if wilcoxon_result is not None else 1.0
        except Exception:
            w = np.nan
            p = 1.0
        point_b, point_s = score_summary(base), score_summary(safe)
        effects.append({"model": model, **{f"baseline_{k}": v for k, v in point_b.items()}, **{f"safety_{k}": v for k, v in point_s.items()},
                        "delta_norm": 50 * (base.mean() - safe.mean()),
                        "delta_poll": point_s["polluted_rate"] - point_b["polluted_rate"],
                        "delta_recognised": point_s["recognised_rate"] - point_b["recognised_rate"],
                        "wilcoxon_w": w, "wilcoxon_p": p, "ci_method": "paired item bootstrap", "rerun_groups": int(majority[(majority.model == model) & majority.is_rerun].shape[0]), **paired_item_bootstrap(base, safe, rng)})
    effects = pd.DataFrame(effects)
    effects["wilcoxon_q_bh"] = bh_qvalues(effects["wilcoxon_p"])
    effects.sort_values("delta_norm", ascending=False).to_csv(TABLES / "prompt_effects_v3.csv", index=False)
    pooled = []
    mats = {}
    for condition in ["baseline", "safety"]:
        m = majority[majority.condition == condition].pivot(index="item_id", columns="model", values="majority_score").sort_index()
        mats[condition] = m
        p = score_summary(m.to_numpy().ravel())
        pooled.append({"condition": condition, **p, **item_bootstrap(m.to_numpy(), rng)})
    b, s = mats["baseline"].to_numpy(), mats["safety"].to_numpy()
    paired = paired_item_bootstrap(b, s, rng)
    pooled_df = pd.DataFrame(pooled)
    pooled_df.to_csv(TABLES / "pooled_results_v3.csv", index=False)
    two_way = two_way_bootstrap(b, s, rng)
    write_json(TABLES / "pooled_prompt_effect_ci_v3.json", {"item_cluster": paired, "two_way_model_item": two_way, "point_delta_norm": 50 * (b.mean() - s.mean()), "point_delta_poll": float((s == 1).mean() - (b == 1).mean()), "point_delta_recognised": float((s == -1).mean() - (b == -1).mean())})
    return effects, pooled_df


def make_judge_agreement(judgments: pd.DataFrame, majority: pd.DataFrame) -> dict:
    n = len(majority)
    pair = []
    for a, b in [("gpt55", "opus47"), ("gpt55", "gemini31pro"), ("opus47", "gemini31pro")]:
        x = judgments[judgments.judge == a].set_index(["model", "condition", "item_id"])["score"]
        y = judgments[judgments.judge == b].set_index(["model", "condition", "item_id"])["score"]
        pair.append({"judge_a": a, "judge_b": b, "agreement_rate": float((x == y).mean()), "n": int((x == y).notna().sum())})
    marg = Counter(judgments["label"])
    pbar = 0.0
    for _, g in judgments.groupby(["model", "condition", "item_id"]):
        c = Counter(g["label"])
        pbar += (sum(v * v for v in c.values()) - 3) / 6
    pbar /= n
    pe = sum((marg[label] / (n * 3)) ** 2 for label in LABELS)
    kappa = (pbar - pe) / (1 - pe) if pe < 1 else np.nan
    out = {"groups": n, "unanimous_groups": int((majority.stratum == "unanimous").sum()), "disagreement_groups": int((majority.stratum != "unanimous").sum()), "fleiss_kappa": float(kappa), "pairwise": pair}
    write_json(TABLES / "judge_agreement_v3.json", out)
    return out


def make_sensitivity(majority: pd.DataFrame) -> None:
    rows = []
    for (model, condition), g in majority.groupby(["model", "condition"], sort=True):
        n = len(g)
        counts = g["majority_label"].value_counts().to_dict()
        for scheme, weights in SENSITIVITY_SCHEMES.items():
            poll = counts.get("Polluted", 0) / n
            vals = [weights[label] for label in g["majority_label"]]
            lo, hi = min(weights.values()), max(weights.values())
            score = 100 * (hi - float(np.mean(vals))) / (hi - lo)
            rows.append({"scheme": scheme, "model": model, "condition": condition, "score": score, "polluted_rate": poll})
    df = pd.DataFrame(rows)
    df["rank"] = df.groupby(["scheme", "condition"])["score"].rank(ascending=False, method="min")
    df.to_csv(TABLES / "normalised_score_sensitivity_v3.csv", index=False)
    base = df[df.scheme == "default"].set_index(["model", "condition"])["rank"]
    rank_rows = []
    for scheme in SENSITIVITY_SCHEMES:
        if scheme == "default":
            continue
        other = df[df.scheme == scheme].set_index(["model", "condition"])["rank"]
        for condition in ["baseline", "safety"]:
            common = base[base.index.get_level_values("condition") == condition].index.intersection(other[other.index.get_level_values("condition") == condition].index)
            rho = spearmanr(base.loc[common], other.loc[common]).statistic if len(common) > 2 else np.nan
            rank_rows.append({"scheme": scheme, "condition": condition, "spearman_rank_vs_default": float(rho)})
    pd.DataFrame(rank_rows).to_csv(TABLES / "normalised_score_rank_stability_v3.csv", index=False)
    # Intervention effect under every scheme.
    effects = []
    for scheme in SENSITIVITY_SCHEMES:
        pivot = df[df.scheme == scheme].pivot(index="model", columns="condition", values="score")
        for model, row in pivot.iterrows():
            effects.append({"scheme": scheme, "model": model, "delta_safety_minus_baseline": float(row["safety"] - row["baseline"])})
    pd.DataFrame(effects).to_csv(TABLES / "normalised_score_intervention_sensitivity_v3.csv", index=False)


def make_theme_and_item_tables(majority: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    base = majority[majority.condition == "baseline"].copy()
    item = base.groupby("item_id").agg(
        study_title=("study_title", "first"), polluted_count=("majority_score", lambda x: int((x == 1).sum())),
        recognised_count=("majority_score", lambda x: int((x == -1).sum())), neutral_count=("majority_score", lambda x: int((x == 0).sum())),
        model_count=("model", "nunique"),
    ).reset_index()
    item["polluted_rate"] = item.polluted_count / item.model_count
    item["recognised_rate"] = item.recognised_count / item.model_count
    item = item.merge(meta[["item_id", "Title_New", "citations", "retraction_date_meta", "theme", "theme_assignment_method", "Condition (disease)"]], on="item_id", how="left")
    item["years_since_retraction"] = (ANALYSIS_DATE - item["retraction_date_meta"]).dt.days / 365.25
    item.to_csv(TABLES / "item_level_baseline_v3.csv", index=False)
    theme = item.groupby("theme").agg(items=("item_id", "nunique"), total_polluted=("polluted_count", "sum"), max_polluted_models=("polluted_count", "max"), total_recognised=("recognised_count", "sum"), mean_polluted_rate=("polluted_rate", "mean")).reset_index()
    theme["items_polluted_by_9plus_models"] = theme["theme"].map(item[item.polluted_count >= 9].groupby("theme").size()).fillna(0).astype(int)
    theme.sort_values(["total_polluted", "items"], ascending=False).to_csv(TABLES / "theme_summary_v3.csv", index=False)
    item[["item_id", "study_title", "theme", "theme_assignment_method"]].to_csv(TABLES / "item_theme_assignments_v3.csv", index=False)
    return item


def make_citation_summary(meta: pd.DataFrame) -> dict[str, float | int | str]:
    citations = pd.to_numeric(meta["citations"], errors="coerce")
    summary = {
        "cohort": "top-100 most-cited retracted RCTs",
        "item_count": int(len(meta)),
        "items_with_citation_count": int(citations.notna().sum()),
        "total_citations": int(citations.sum()),
        "mean_citations": float(citations.mean()),
        "median_citations": float(citations.median()),
        "minimum_citations": int(citations.min()),
        "maximum_citations": int(citations.max()),
    }
    write_json(TABLES / "cohort_citation_summary_v3.json", summary)
    return summary


def make_citation_temporal_fdr(item: pd.DataFrame, majority: pd.DataFrame) -> pd.DataFrame:
    tests = []
    def add(name, family, method, effect_name, effect_estimate, effect_unit,
            statistic_name, statistic, p=np.nan, note="",
            sample_unit="benchmark item", direction="two-sided"):
        tests.append({
            "test": name, "family": family, "method": method,
            "sample_unit": sample_unit, "direction": direction,
            "effect_name": effect_name, "effect_estimate": effect_estimate,
            "effect_unit": effect_unit, "statistic_name": statistic_name,
            "statistic": statistic, "raw_p": p, "note": note,
        })
    # Citation associations and tertile trends.
    for outcome in ["polluted_rate", "recognised_rate", "neutral_count"]:
        y = item[outcome] if outcome != "neutral_count" else item.neutral_count / item.model_count
        mask = item.citations.notna() & y.notna()
        rho, p = spearmanr(item.loc[mask, "citations"], y[mask])
        add(f"citation_spearman_{outcome}", "exploratory_citation_temporal_subgroup_regression", "Spearman item-level baseline rate vs citations", f"citation association with {outcome}", float(rho), "Spearman rho", "Spearman rho", float(rho), float(p))
    item["citation_tertile"] = pd.qcut(item["citations"], 3, labels=[1, 2, 3], duplicates="drop").astype(float)
    for outcome in ["polluted_rate", "recognised_rate"]:
        mask = item.citation_tertile.notna()
        rho, p = spearmanr(item.loc[mask, "citation_tertile"], item.loc[mask, outcome])
        add(f"citation_tertile_trend_{outcome}", "exploratory_citation_temporal_subgroup_regression", "Spearman tertile rank vs item rate", f"citation-tertile association with {outcome}", float(rho), "Spearman rho", "Spearman rho", float(rho), float(p))
    high = item[item.citation_tertile == item.citation_tertile.max()].sort_values("citations")
    low10, top10 = high.head(10), high.tail(10)
    for outcome in ["polluted_rate", "recognised_rate"]:
        stat, p = mannwhitneyu(top10[outcome], low10[outcome], alternative="two-sided")
        effect = float(top10[outcome].mean() - low10[outcome].mean())
        add(f"high_tertile_top10_vs_bottom10_{outcome}", "exploratory_citation_temporal_subgroup_regression", "Mann-Whitney U on item rates", f"top-minus-bottom mean {outcome}", effect, "proportion", "Mann-Whitney U_top", float(stat), float(p))
    # Temporal associations.
    for outcome in ["polluted_rate", "recognised_rate"]:
        mask = item.years_since_retraction.notna()
        rho, p = spearmanr(item.loc[mask, "years_since_retraction"], item.loc[mask, outcome])
        add(f"temporal_spearman_{outcome}", "exploratory_citation_temporal_subgroup_regression", "Spearman years since retraction vs item rate", f"temporal association with {outcome}", float(rho), "Spearman rho", "Spearman rho", float(rho), float(p))
    item["early_retraction"] = item["retraction_date_meta"].dt.year < 2021
    for outcome in ["polluted_rate", "recognised_rate"]:
        a = item.loc[item.early_retraction, outcome].dropna(); b = item.loc[~item.early_retraction, outcome].dropna()
        stat, p = mannwhitneyu(a, b, alternative="two-sided")
        effect = float(a.mean() - b.mean())
        add(f"temporal_before2021_vs_2021plus_{outcome}", "exploratory_citation_temporal_subgroup_regression", "Mann-Whitney U on item rates", f"pre-2021-minus-2021+ mean {outcome}", effect, "proportion", "Mann-Whitney U_pre-2021", float(stat), float(p))
    # Exploratory adjusted OLS with the auditable locked theme mapping.
    if smf is not None:
        reg = item.dropna(subset=["years_since_retraction", "citations"]).copy()
        reg["log_citations"] = np.log1p(reg["citations"])
        for outcome in ["polluted_rate", "recognised_rate"]:
            fit = smf.ols(f"{outcome} ~ years_since_retraction + log_citations + C(theme)", data=reg).fit()
            add(f"ols_years_coefficient_{outcome}", "exploratory_citation_temporal_subgroup_regression", "OLS with log citations and locked theme fixed effects", "OLS beta for years_since_retraction", float(fit.params["years_since_retraction"]), "outcome-rate change per year", "OLS t", float(fit.tvalues["years_since_retraction"]), float(fit.pvalues["years_since_retraction"]), f"n={len(reg)}")
    else:
        for outcome in ["polluted_rate", "recognised_rate"]:
            add(f"ols_years_coefficient_{outcome}", "exploratory_citation_temporal_subgroup_regression", "unavailable", "OLS beta for years_since_retraction", np.nan, "outcome-rate change per year", "OLS t", np.nan, note="statsmodels unavailable")
    # Self-preference is kept as a separate descriptive family.
    provider_models = {"gpt55": "gpt-5.5-2026-04-23", "opus47": "claude-opus-4-7default", "gemini31pro": "google_gemini-3.1-pro-preview"}
    self_rows = []
    for judge, model in provider_models.items():
        g = majority[(majority.model == model)]
        # Use judge-level scores, not majority scores.
        # The caller attaches judge data separately below; this placeholder is replaced in main.
    return pd.DataFrame(tests)


def make_human_validation(majority: pd.DataFrame) -> pd.DataFrame:
    master = read_xlsx_rows(MASTER_PATH, "sample_manifest")
    a = read_xlsx_rows(RATER_A_PATH)
    b = read_xlsx_rows(RATER_B_PATH)
    adjud = read_xlsx_rows(ADJUDICATION_PATH, "human_label不一致清单", 50)
    required = {"sample_id", "human_label"}
    if not required.issubset(a.columns) or not required.issubset(b.columns):
        raise ValueError("human blind workbook missing human_label")
    if set(a.sample_id) != set(b.sample_id) or len(a) != 140 or len(b) != 140 or len(master) != 140:
        raise ValueError("human/master sample count or IDs do not match")
    illegal = (set(a.human_label) | set(b.human_label)) - set(RATER_LABELS)
    if illegal:
        raise ValueError(f"unexpected rater labels: {sorted(illegal)}")
    # A discrepant pair or either annotator's `Unclear` routes the row to the adjudicator.
    needs_adjudication = set(
        a.loc[(a.human_label.to_numpy() != b.human_label.to_numpy())
              | a.human_label.eq("Unclear").to_numpy()
              | b.human_label.eq("Unclear").to_numpy(), "sample_id"]
    )
    if set(adjud.sample_id) != needs_adjudication:
        raise ValueError("adjudication summary does not exactly cover A/B disagreements")
    if set(adjud["结论"]) - set(LABELS):
        raise ValueError("adjudicated labels must be one of the three final labels")

    # Keep the locked sample IDs, but refresh cell sizes and inverse-probability
    # weights against the final post-patch automated population.  A label change
    # outside the sample can alter N_h even when no sampled row changed.
    population = majority.copy()
    population["sampling_stratum"] = np.where(
        population["stratum"].eq("unanimous"),
        "unanimous_" + population["majority_label"].str.lower(),
        "any_disagreement",
    )
    population_counts = population.groupby(["sampling_stratum", "condition"]).size().to_dict()
    sample_counts = master.groupby(["stratum", "condition"]).size().to_dict()
    master["population_cell_n"] = [
        population_counts[(row.stratum, row.condition)] for row in master.itertuples()
    ]
    master["sample_cell_n"] = [
        sample_counts[(row.stratum, row.condition)] for row in master.itertuples()
    ]
    master["inclusion_probability"] = master["sample_cell_n"] / master["population_cell_n"]
    master["design_weight"] = 1.0 / master["inclusion_probability"]
    master.to_csv(HUMAN_OUT / "n140_sampling_manifest_postpatch_v3.csv", index=False)
    allocation_rows = [
        {
            "stratum": stratum,
            "condition": condition,
            "population_n": population_counts[(stratum, condition)],
            "sample_n": sample_counts[(stratum, condition)],
            "inclusion_probability": sample_counts[(stratum, condition)] / population_counts[(stratum, condition)],
            "design_weight": population_counts[(stratum, condition)] / sample_counts[(stratum, condition)],
        }
        for stratum, condition in sorted(population_counts)
    ]
    corrected_workbook = HUMAN_OUT / "n140_master_unblinded_postpatch_v3.xlsx"
    with pd.ExcelWriter(corrected_workbook, engine="openpyxl") as writer:
        master.to_excel(writer, sheet_name="sample_manifest", index=False)
        pd.DataFrame(allocation_rows).to_excel(writer, sheet_name="allocation_summary", index=False)
        writer.book.properties.creator = "V3 analysis pipeline"
        writer.book.properties.lastModifiedBy = "V3 analysis pipeline"
        for worksheet in writer.book.worksheets:
            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions

    final_map = dict(zip(adjud.sample_id, adjud["结论"]))
    master_cols = ["sample_id", "model", "condition", "item_id", "label", "stratum", "design_weight", "inclusion_probability"]
    h = master[master_cols].copy().rename(columns={"label": "master_row_label", "item_id": "benchmark_item_id"})
    # The master workbook stores the selected judge row's label in `label`; for
    # validation it must be replaced by the three-judge majority label.
    h = h.merge(majority[["model", "condition", "item_id", "majority_label"]], left_on=["model", "condition", "benchmark_item_id"], right_on=["model", "condition", "item_id"], how="left", validate="one_to_one")
    if h["majority_label"].isna().any():
        raise ValueError("human sample could not be matched to majority labels")
    h = h.rename(columns={"majority_label": "automated_label"}).drop(columns=["item_id"])
    h = h.merge(a.add_prefix("a_").rename(columns={"a_sample_id": "sample_id"}), on="sample_id", how="left")
    h = h.merge(b.add_prefix("b_").rename(columns={"b_sample_id": "sample_id"}), on="sample_id", how="left")
    h["human_label_final"] = [final_map.get(sid, a_label) for sid, a_label in zip(h.sample_id, h.a_human_label)]
    if set(h.human_label_final) - set(LABELS):
        raise ValueError("final human labels must be resolved to the three-class rubric")
    h["adjudicated"] = h.sample_id.isin(final_map)
    h["ab_agree"] = h.a_human_label == h.b_human_label
    h["human_auto_agree"] = h.human_label_final == h.automated_label
    h.to_csv(HUMAN_OUT / "human_label_resolution_v3.csv", index=False)
    # A/B agreement and confusion.  `Unclear` is retained so the matrix totals 140.
    ab_conf = pd.crosstab(a.human_label, b.human_label).reindex(index=RATER_LABELS, columns=RATER_LABELS, fill_value=0)
    ab_conf = ab_conf.loc[ab_conf.sum(axis=1) > 0, ab_conf.sum(axis=0) > 0]
    ab_conf.to_csv(HUMAN_OUT / "human_human_confusion_unweighted_v3.csv")
    # Weighted human-vs-automated confusion and population distributions.
    conf = pd.pivot_table(h, index="automated_label", columns="human_label_final", values="design_weight", aggfunc="sum", fill_value=0).reindex(index=LABELS, columns=LABELS, fill_value=0)
    conf.to_csv(HUMAN_OUT / "automated_human_confusion_weighted_v3.csv")
    # Calibrate the row totals to the complete automated population margins while
    # retaining the design-weighted P(human label | automated label) estimates.
    population_margins = majority["majority_label"].value_counts().reindex(LABELS, fill_value=0).astype(float)
    conditional = conf.div(conf.sum(axis=1).replace(0, np.nan), axis=0).fillna(0)
    calibrated_conf = conditional.mul(population_margins, axis=0)
    calibrated_conf.to_csv(HUMAN_OUT / "automated_human_confusion_calibrated_v3.csv")
    direct_ipw_agreement = float(np.trace(conf.to_numpy(float)) / conf.to_numpy(float).sum())
    calibrated_agreement = float(np.trace(calibrated_conf.to_numpy(float)) / population_margins.sum())
    write_json(HUMAN_OUT / "human_validation_calibrated_agreement_v3.json", {
        "n_validation": len(h),
        "primary_estimator": "direct IPW",
        "direct_ipw_agreement_primary": direct_ipw_agreement,
        "sensitivity_estimator": "post-stratified to known automated-label margins",
        "poststratified_agreement_sensitivity": calibrated_agreement,
        "automated_population_margins": {label: int(population_margins[label]) for label in LABELS},
    })
    # Rater C was blinded to the automated labels, but the adjudication instrument showed both
    # annotators' labels, so an adjudicated row resolves to one of those two rather than to an
    # independent third reading.  Quantify how far the estimate can move on the rows C decided;
    # rows where A and B already agreed never reached C.
    adjudicated = h.adjudicated.to_numpy(bool)
    agree_row = (h.human_label_final == h.automated_label).to_numpy(float)
    weight = h.design_weight.to_numpy(float)
    concordant_weight = weight[~adjudicated].sum()
    concordant_agreeing = (agree_row[~adjudicated] * weight[~adjudicated]).sum()
    auto_available = sum(
        1 for adj, auto_label, a_label, b_label in
        zip(adjudicated, h.automated_label, h.a_human_label, h.b_human_label)
        if adj and auto_label in (a_label, b_label)
    )
    write_json(HUMAN_OUT / "human_validation_adjudication_sensitivity_v3.json", {
        "n_adjudicated": int(adjudicated.sum()),
        "adjudicated_population_weight_share": float(weight[adjudicated].sum() / weight.sum()),
        "primary_agreement_all_rows": direct_ipw_agreement,
        "agreement_on_ab_concordant_rows_only": float(concordant_agreeing / concordant_weight),
        "lower_bound_all_adjudicated_counted_as_disagreement": float(concordant_agreeing / weight.sum()),
        "upper_bound_all_adjudicated_counted_as_agreement": float((concordant_agreeing + weight[adjudicated].sum()) / weight.sum()),
        "adjudicated_rows_matching_automated_label": int(agree_row[adjudicated].sum()),
        "adjudicated_rows_where_automated_label_was_an_available_option": auto_available,
    })
    # Secondary fields: report rater distributions and agreement; consensus-only values are explicit.
    # Two of the four fields are scoped by the frozen rubric: neutral_subtype is answered only when
    # the rater's own primary label is Neutral, and conclusion_overlap only when the rater did not
    # find the target article cited or identified.  Outside that scope both raters enter
    # "Not applicable", so those cells agree by construction.  Reporting the whole-sample agreement
    # alone would therefore present a deterministic match as a reliability estimate; we additionally
    # report the denominator on which each field was actually answered by both raters.
    not_applicable = "Not applicable"
    for field, permitted in PERMITTED_SECONDARY_VALUES.items():
        af, bf = f"a_{field}", f"b_{field}"
        a_values = h[af].astype(str)
        b_values = h[bf].astype(str)
        observed = sorted(set(a_values) | set(b_values))
        unexpected = [value for value in observed if value not in permitted]
        if unexpected:
            raise ValueError(f"{field} carries values outside the frozen rubric: {unexpected}")
        # Permitted-but-unused values are retained with a zero count so that a null result stays visible.
        pd.DataFrame({
            "value": permitted,
            "a_n": [int((a_values == value).sum()) for value in permitted],
            "b_n": [int((b_values == value).sum()) for value in permitted],
        }).to_csv(HUMAN_OUT / f"secondary_{field}_rater_distributions_v3.csv", index=False)
    sec_rows = []
    for field in PERMITTED_SECONDARY_VALUES:
        af, bf = f"a_{field}", f"b_{field}"
        a_values = h[af].astype(str)
        b_values = h[bf].astype(str)
        agree = a_values == b_values
        both_na = (a_values == not_applicable) & (b_values == not_applicable)
        applicable = (a_values != not_applicable) & (b_values != not_applicable)
        applicable_agree = agree & applicable
        sec_rows.append({
            "field": field,
            "n": len(h),
            "ab_agreement_n": int(agree.sum()),
            "ab_agreement_rate": float(agree.mean()),
            "both_not_applicable_n": int(both_na.sum()),
            "applicable_both_n": int(applicable.sum()),
            "applicable_agreement_n": int(applicable_agree.sum()),
            "applicable_agreement_rate": (float(applicable_agree.sum() / applicable.sum()) if int(applicable.sum()) else float("nan")),
            "a_distribution": json.dumps(Counter(h[af].fillna("NA")), ensure_ascii=False),
            "b_distribution": json.dumps(Counter(h[bf].fillna("NA")), ensure_ascii=False),
        })
    pd.DataFrame(sec_rows).to_csv(HUMAN_OUT / "secondary_field_agreement_v3.csv", index=False)
    # Weighted point summaries.
    weighted = []
    for scope_name, sub in [("overall", h), *[(f"stratum:{x}", h[h.stratum == x]) for x in sorted(h.stratum.unique())], *[(f"condition:{x}", h[h.condition == x]) for x in sorted(h.condition.unique())]]:
        den = sub.design_weight.sum()
        weighted.append({"scope": scope_name, "n_sample": len(sub), "population_weight_sum": float(den), "automated_agreement_weighted": float(sub.loc[sub.human_auto_agree, "design_weight"].sum() / den), **{f"human_{lab.lower()}_weighted": float(sub.loc[sub.human_label_final == lab, "design_weight"].sum() / den) for lab in LABELS}, **{f"automated_{lab.lower()}_weighted": float(sub.loc[sub.automated_label == lab, "design_weight"].sum() / den) for lab in LABELS}})
    pd.DataFrame(weighted).to_csv(HUMAN_OUT / "human_validation_weighted_summary_v3.csv", index=False)
    # The judge-disagreement stratum was deliberately oversampled and is the only stratum with low
    # agreement, so the estimate is sensitive to which automated labels the draw happened to pick up
    # inside it.  That composition is a known population quantity, so we post-stratify within the
    # stratum to the known automated-label counts and report how far the overall estimate moves.
    disagreement_population = (
        majority.loc[majority.stratum.ne("unanimous"), "majority_label"]
        .value_counts()
        .reindex(LABELS, fill_value=0)
    )
    disagreement_sample = h[h.stratum.eq("any_disagreement")]
    cell_rows = []
    for label in LABELS:
        cell = disagreement_sample[disagreement_sample.automated_label.eq(label)]
        cell_weight = cell.design_weight.sum()
        cell_rows.append({
            "automated_label": label,
            "sample_n": int(len(cell)),
            "population_n": int(disagreement_population[label]),
            "population_share": float(disagreement_population[label] / disagreement_population.sum()),
            "sample_share": float(len(cell) / len(disagreement_sample)) if len(disagreement_sample) else float("nan"),
            "agreement_design_weighted": (float(cell.loc[cell.human_auto_agree, "design_weight"].sum() / cell_weight) if cell_weight else float("nan")),
            "agreement_unweighted": (float(cell.human_auto_agree.mean()) if len(cell) else float("nan")),
        })
    cells_frame = pd.DataFrame(cell_rows)
    cells_frame.to_csv(HUMAN_OUT / "human_validation_disagreement_poststratification_v3.csv", index=False)
    estimable = cells_frame.dropna(subset=["agreement_design_weighted"])
    stratum_poststratified = float(
        (estimable.population_n * estimable.agreement_design_weighted).sum() / estimable.population_n.sum()
    )
    stratum_as_published = float(
        disagreement_sample.loc[disagreement_sample.human_auto_agree, "design_weight"].sum()
        / disagreement_sample.design_weight.sum()
    )
    other_strata = h[h.stratum.ne("any_disagreement")]
    overall_poststratified = float(
        (other_strata.loc[other_strata.human_auto_agree, "design_weight"].sum()
         + stratum_poststratified * float(disagreement_population.sum()))
        / h.design_weight.sum()
    )
    write_json(HUMAN_OUT / "human_validation_disagreement_poststratification_v3.json", {
        "stratum": "any_disagreement",
        "population_n": int(disagreement_population.sum()),
        "sample_n": int(len(disagreement_sample)),
        "population_composition": {label: int(disagreement_population[label]) for label in LABELS},
        "sample_composition": {row["automated_label"]: row["sample_n"] for row in cell_rows},
        "stratum_agreement_as_published": stratum_as_published,
        "stratum_agreement_post_stratified": stratum_poststratified,
        "overall_agreement_as_published": direct_ipw_agreement,
        "overall_agreement_post_stratified": overall_poststratified,
    })
    # Within-cell weighted bootstrap for overall metrics and label rates.
    rng = np.random.default_rng(SEED + 100)
    cells = [g for _, g in h.groupby(["stratum", "condition"], sort=True)]
    boot = {"agreement": [], **{f"human_{lab}": [] for lab in LABELS}, **{f"auto_{lab}": [] for lab in LABELS}, **{f"adjusted_{lab}": [] for lab in LABELS}}
    population_auto = majority["majority_label"].value_counts(normalize=True).reindex(LABELS, fill_value=0).to_numpy(float)
    point_conf = pd.pivot_table(h, index="automated_label", columns="human_label_final", values="design_weight", aggfunc="sum", fill_value=0).reindex(index=LABELS, columns=LABELS, fill_value=0)
    point_cond = point_conf.div(point_conf.sum(axis=1).replace(0, np.nan), axis=0).fillna(0).to_numpy(float)
    point_adjusted = dict(zip(LABELS, population_auto @ point_cond))
    for _ in range(BOOTSTRAP):
        chosen = []
        for g in cells:
            chosen.append(g.iloc[rng.integers(0, len(g), len(g))])
        z = pd.concat(chosen, ignore_index=True)
        den = z.design_weight.sum()
        boot["agreement"].append(float(z.loc[z.human_auto_agree, "design_weight"].sum() / den))
        for lab in LABELS:
            boot[f"human_{lab}"].append(float(z.loc[z.human_label_final == lab, "design_weight"].sum() / den))
            boot[f"auto_{lab}"].append(float(z.loc[z.automated_label == lab, "design_weight"].sum() / den))
        zconf = pd.pivot_table(z, index="automated_label", columns="human_label_final", values="design_weight", aggfunc="sum", fill_value=0).reindex(index=LABELS, columns=LABELS, fill_value=0)
        zcond = zconf.div(zconf.sum(axis=1).replace(0, np.nan), axis=0).fillna(0).to_numpy(float)
        adjusted = population_auto @ zcond
        for lab, value in zip(LABELS, adjusted):
            boot[f"adjusted_{lab}"].append(float(value))
    cis = []
    point = weighted[0]
    for metric, vals in boot.items():
        if metric == "agreement":
            est = point["automated_agreement_weighted"]
        elif metric.startswith("adjusted_"):
            est = point_adjusted[metric.removeprefix("adjusted_")]
        else:
            key = metric.lower().replace("auto_", "automated_") + "_weighted"
            est = point.get(key, np.nan)
        cis.append({"metric": metric, "estimate": est, "ci_low": float(np.quantile(vals, 0.025)), "ci_high": float(np.quantile(vals, 0.975))})
    pd.DataFrame(cis).to_csv(HUMAN_OUT / "human_validation_weighted_bootstrap_ci_v3.csv", index=False)
    # Human-human agreement and label-level agreement.
    kappa = cohen_kappa(h.a_human_label, h.b_human_label)
    kappa_low, kappa_high = paired_kappa_bootstrap(
        h.a_human_label, h.b_human_label, np.random.default_rng(SEED + 101)
    )
    raw = {"n": len(h), "ab_agreement_n": int(h.ab_agree.sum()), "ab_agreement_rate": float(h.ab_agree.mean()), "cohen_kappa_ab": kappa, "cohen_kappa_ab_ci_low": kappa_low, "cohen_kappa_ab_ci_high": kappa_high, "adjudicated_n": int(h.adjudicated.sum()), "final_label_counts": dict(Counter(h.human_label_final)), "automated_label_counts": dict(Counter(h.automated_label))}
    write_json(HUMAN_OUT / "human_validation_agreement_v3.json", raw)
    # Reference-adjusted three-class rates and correction matrix P(H | automated).
    cond = conditional
    cond.to_csv(HUMAN_OUT / "human_given_automated_conditional_v3.csv")
    sample_auto = weighted_distribution(h, "automated_label")
    ref = weighted_distribution(h, "human_label_final")
    population_auto = majority["majority_label"].value_counts(normalize=True).reindex(LABELS, fill_value=0).to_numpy(float)
    adjusted = population_auto @ cond.reindex(index=LABELS, columns=LABELS, fill_value=0).to_numpy(float)
    adjusted_dict = dict(zip(LABELS, adjusted))
    write_json(HUMAN_OUT / "human_reference_adjusted_rates_v3.json", {"automated_population_observed": dict(zip(LABELS, population_auto)), "automated_sample_design_weighted": sample_auto, "human_design_weighted_direct": ref, "reference_adjusted_from_population_automated": adjusted_dict, "difference_adjusted_minus_automated_population": {lab: adjusted_dict[lab] - population_auto[i] for i, lab in enumerate(LABELS)}, "conditional_human_given_automated": cond.to_dict()})
    return h


def make_self_preference(judgments: pd.DataFrame) -> pd.DataFrame:
    pairs = {"gpt55": "gpt-5.5-2026-04-23", "opus47": "claude-opus-4-7default", "gemini31pro": "google_gemini-3.1-pro-preview"}
    rows = []
    for judge, model in pairs.items():
        own = judgments[(judgments.model == model) & (judgments.judge == judge)].set_index(["condition", "item_id"])["score"]
        others = judgments[(judgments.model == model) & (judgments.judge != judge)].groupby(["condition", "item_id"])["score"].mean()
        idx = own.index.intersection(others.index)
        x, y = own.loc[idx].to_numpy(float), others.loc[idx].to_numpy(float)
        d = x - y
        try:
            wp = float(wilcoxon(d).pvalue) if np.any(d != 0) else 1.0
        except Exception:
            wp = 1.0
        tp = float(ttest_rel(x, y).pvalue) if len(x) > 1 else np.nan
        rows.append({"judge_family": judge, "model": model, "n_observations": len(x), "mean_own_family_score": float(x.mean()), "mean_other_judges_score": float(y.mean()), "delta_own_minus_other": float(d.mean()), "polluted_rate_difference": float((x == 1).mean() - (y == 1).mean()), "recognised_rate_difference": float((x == -1).mean() - (y == -1).mean()), "paired_t_p": tp, "wilcoxon_p": wp})
    out = pd.DataFrame(rows)
    out["wilcoxon_q_bh"] = bh_qvalues(out.wilcoxon_p)
    out.to_csv(TABLES / "self_preference_v3.csv", index=False)
    return out


def generate_figures(majority: pd.DataFrame, item: pd.DataFrame) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    models = sorted(majority.model.unique())
    display = {"Baichuan-M3":"Baichuan-M3", "Kimi-K2.6":"Kimi K2.6", "claude-opus-4-7default":"Claude Opus 4.7", "claude-sonnet-4-6default":"Claude Sonnet 4.6", "deepseek-r1-0528":"DeepSeek-R1-0528", "deepseek-v4-flash":"DeepSeek-V4 Flash", "deepseek-v4-pro":"DeepSeek-V4 Pro", "gemini-2.5-flash":"Gemini 2.5 Flash", "google_gemini-3.1-pro-preview":"Gemini 3.1 Pro", "gpt-5.4-2026-03-05":"GPT-5.4", "gpt-5.4-nano-2026-03-17":"GPT-5.4 Nano", "gpt-5.5-2026-04-23":"GPT-5.5", "minimaxai-minimax-m2.7":"MiniMax M2.7", "z-ai_glm-5.1":"GLM-5.1"}
    # Heatmap: baseline polluted count by title-derived theme.
    base = majority[majority.condition == "baseline"].copy().merge(item[["item_id", "theme"]], on="item_id", how="left")
    tab = base.assign(poll=(base.majority_score == 1).astype(int)).pivot_table(index="theme", columns="model", values="poll", aggfunc="sum", fill_value=0)
    tab = tab.loc[tab.sum(axis=1).sort_values(ascending=False).index, :]
    tab = tab.loc[:, tab.sum(axis=0).sort_values(ascending=False).index]
    fig, ax = plt.subplots(figsize=(9, 5.2))
    im = ax.imshow(tab.values, aspect="auto", cmap="Blues", vmin=0)
    ax.set_yticks(range(len(tab.index))); ax.set_yticklabels(tab.index, fontsize=8)
    ax.set_xticks(range(len(tab.columns))); ax.set_xticklabels([display.get(x, x) for x in tab.columns], rotation=45, ha="right", fontsize=7)
    for i in range(tab.shape[0]):
        for j in range(tab.shape[1]):
            ax.text(j, i, int(tab.iloc[i, j]), ha="center", va="center", fontsize=6, color="white" if tab.iloc[i,j] > tab.values.max()*0.55 else "black")
    ax.set_xlabel("Model"); ax.set_ylabel("Title-derived thematic group")
    fig.colorbar(im, ax=ax, label="Polluted baseline labels")
    fig.tight_layout(); fig.savefig(FIGURES / "polluted_heatmap_v3.png", dpi=300); fig.savefig(FIGURES / "polluted_heatmap_v3.pdf"); plt.close(fig)
    # Rates and prompt effect.
    sums = majority.groupby(["model", "condition"])["majority_score"].agg(n="size", polluted=lambda x: (x==1).sum(), recognised=lambda x: (x==-1).sum()).reset_index()
    sums["polluted_rate"] = sums.polluted / sums.n; sums["recognised_rate"] = sums.recognised / sums.n
    order = sums[sums.condition == "baseline"].sort_values("polluted_rate").model.tolist()
    fig, ax = plt.subplots(figsize=(8, 5))
    x = np.arange(len(order)); b = sums[sums.condition == "baseline"].set_index("model").loc[order]; s = sums[sums.condition == "safety"].set_index("model").loc[order]
    ax.bar(x-0.18, b.polluted_rate*100, 0.36, label="Baseline", color="#b2182b"); ax.bar(x+0.18, s.polluted_rate*100, 0.36, label="Safety package", color="#1b7837")
    ax.set_xticks(x); ax.set_xticklabels([display.get(m,m) for m in order], rotation=45, ha="right", fontsize=7); ax.set_ylabel("Polluted rate (%)"); ax.legend(frameon=False); fig.tight_layout(); fig.savefig(FIGURES / "polluted_rates_v3.png", dpi=300); fig.savefig(FIGURES / "polluted_rates_v3.pdf"); plt.close(fig)
    # Dumbbell on normalised score.
    norm = majority.groupby(["model", "condition"])["majority_score"].mean().mul(-50).add(50).unstack()
    order = (norm.safety - norm.baseline).sort_values(ascending=False).index.tolist()
    fig, ax = plt.subplots(figsize=(7.5, 5.5)); y = np.arange(len(order))
    for i,m in enumerate(order):
        ax.plot([norm.loc[m,"baseline"], norm.loc[m,"safety"]], [i,i], color="#999999", lw=1)
        ax.scatter(norm.loc[m,"baseline"], i, color="#b2182b", s=20, label="Baseline" if i==0 else None)
        ax.scatter(norm.loc[m,"safety"], i, color="#1b7837", s=20, label="Safety package" if i==0 else None)
    ax.set_yticks(y); ax.set_yticklabels([display.get(m,m) for m in order], fontsize=7); ax.set_xlabel("Normalised score"); ax.legend(frameon=False); fig.tight_layout(); fig.savefig(FIGURES / "prompt_effect_dumbbell_v3.png", dpi=300); fig.savefig(FIGURES / "prompt_effect_dumbbell_v3.pdf"); plt.close(fig)


def write_supplementary(majority: pd.DataFrame, summary: pd.DataFrame, effects: pd.DataFrame, item: pd.DataFrame, human: pd.DataFrame, fdr: pd.DataFrame, judge_agreement: dict) -> None:
    def esc(x: object) -> str:
        return str(x).replace("&", r"\&").replace("%", r"\%").replace("_", r"\_").replace("#", r"\#")
    display_model = {"Baichuan-M3":"Baichuan-M3", "Kimi-K2.6":"Kimi K2.6", "claude-opus-4-7default":"Claude Opus 4.7", "claude-sonnet-4-6default":"Claude Sonnet 4.6", "deepseek-r1-0528":"DeepSeek-R1-0528", "deepseek-v4-flash":"DeepSeek-V4 Flash", "deepseek-v4-pro":"DeepSeek-V4 Pro", "gemini-2.5-flash":"Gemini 2.5 Flash", "google_gemini-3.1-pro-preview":"Gemini 3.1 Pro", "gpt-5.4-2026-03-05":"GPT-5.4", "gpt-5.4-nano-2026-03-17":"GPT-5.4 Nano", "gpt-5.5-2026-04-23":"GPT-5.5", "minimaxai-minimax-m2.7":"MiniMax M2.7", "z-ai_glm-5.1":"GLM-5.1"}
    tex_newline = r"\\"
    lines = [r"\documentclass[10pt]{article}", r"\usepackage[margin=2cm]{geometry}", r"\usepackage{booktabs,longtable,array,graphicx}", r"\usepackage[hidelinks]{hyperref}", r"\setlength{\emergencystretch}{3em}", r"\sloppy", r"\begin{document}", r"\section*{Supplementary Materials}", r"\subsection*{Analysis provenance}", f"All results use the repaired judgment layer (8,400 judge records; 2,800 model-condition-item groups) and the completed n=140 human review. Bootstrap procedures used 10,000 iterations with master seed {SEED} and documented derived streams: {SEED + 1} for prompt-effect analyses, {SEED + 100} for the human weighted bootstrap and {SEED + 101} for the human--human $\\kappa$ bootstrap. The analysis date used for retraction-age summaries is {ANALYSIS_DATE.date()}. Original data and reviewer workbooks were not overwritten.", r"\subsection*{Supplementary Table 1. Automated judge agreement}", r"\begin{tabular}{lr}", r"\toprule Metric & Value \\", r"\midrule"]
    for k in ["groups", "unanimous_groups", "disagreement_groups", "fleiss_kappa"]:
        value = f"{judge_agreement[k]:.3f}" if k == "fleiss_kappa" else str(judge_agreement[k])
        lines.append(f"{esc(k)} & {value} " + tex_newline)
    for p in judge_agreement["pairwise"]:
        lines.append(f"{p['judge_a']}--{p['judge_b']} agreement & {p['agreement_rate']:.4f} " + tex_newline)
    lines += [r"\bottomrule", r"\end{tabular}", r"\subsection*{Supplementary Table 2. Human validation by sampled stratum}", r"Both columns of rates are direct inverse-probability-weighted estimates computed from the n=140 sample alone. The Human Polluted rate here is therefore not the same estimator as the reference-adjusted Polluted rate in Supplementary Table 3, which applies the conditional human-given-automated matrix to the known automated distribution of all 2,800 groups. The two differ by construction (overall 0.220 direct versus 0.216 reference-adjusted) and are not an inconsistency.", r"\par\medskip", r"\begin{tabular}{lrrrr}", r"\toprule Scope & n & Weight sum & Auto--human agreement & Human Polluted rate (direct IPW) \\", r"\midrule"]
    hv = pd.read_csv(HUMAN_OUT / "human_validation_weighted_summary_v3.csv")
    for _, r in hv.iterrows():
        lines.append(f"{esc(r.scope)} & {int(r.n_sample)} & {r.population_weight_sum:.1f} & {r.automated_agreement_weighted:.3f} & {r.human_polluted_weighted:.3f} " + tex_newline)
    ps = json.loads((HUMAN_OUT / "human_validation_disagreement_poststratification_v3.json").read_text())
    ps_cells = pd.read_csv(HUMAN_OUT / "human_validation_disagreement_poststratification_v3.csv")
    human_resolution = pd.read_csv(HUMAN_OUT / "human_label_resolution_v3.csv")
    raw_match_n = int((human_resolution.automated_label == human_resolution.human_label_final).sum())
    raw_match_total = int(len(human_resolution))
    lines += [
        r"\bottomrule",
        r"\end{tabular}",
        r"\par\medskip",
        r"\small",
        f"For reference, the unweighted agreement between the automated majority label and the final "
        f"human label in the drawn sample is {raw_match_n}/{raw_match_total} "
        f"({raw_match_n / raw_match_total:.3f}). That figure is lower than the design-weighted estimate "
        f"of {hv.loc[hv.scope == 'overall', 'automated_agreement_weighted'].iloc[0]:.3f} by construction "
        f"and is not an estimate of population agreement: the draw deliberately over-represents the "
        f"hardest cases, allocating 35 of 140 rows to the judge-disagreement stratum, which holds only "
        f"201 of the 2,800 groups. We report it so that the face-value sample count and the "
        f"design-weighted population estimate are both visible.",
        r"\par\medskip",
        r"\small",
        r"The judge-disagreement stratum was deliberately oversampled and is the only stratum with low "
        r"agreement, so the overall estimate depends on which automated labels the draw happened to pick "
        r"up inside it. That composition is a known population quantity, and the realised draw departed "
        r"from it: "
        + ", ".join(
            f"{esc(row.automated_label)} {int(row.sample_n)} sampled against {int(row.population_n)} in the stratum population"
            for _, row in ps_cells.iterrows()
        )
        + r". Post-stratifying within the stratum to those known counts is reported below. It is a "
        r"sensitivity analysis; the direct inverse-probability estimate remains primary.",
        r"\par\medskip",
        r"\scriptsize",
        r"\begin{tabular}{lrrr}",
        r"\toprule Automated label in stratum & Sampled n & Stratum population N & Design-weighted agreement \\",
        r"\midrule",
    ]
    for _, row in ps_cells.iterrows():
        agreement = f"{row.agreement_design_weighted:.3f}" if row.agreement_design_weighted == row.agreement_design_weighted else "not estimable"
        lines.append(
            f"{esc(row.automated_label)} & {int(row.sample_n)} & {int(row.population_n)} & {agreement} " + tex_newline
        )
    lines += [
        r"\midrule",
        f"Stratum agreement, as published & {int(ps['sample_n'])} & {int(ps['population_n'])} & {ps['stratum_agreement_as_published']:.3f} " + tex_newline,
        f"Stratum agreement, post-stratified & {int(ps['sample_n'])} & {int(ps['population_n'])} & {ps['stratum_agreement_post_stratified']:.3f} " + tex_newline,
        f"Overall agreement, as published & 140 & 2800 & {ps['overall_agreement_as_published']:.3f} " + tex_newline,
        f"Overall agreement, post-stratified & 140 & 2800 & {ps['overall_agreement_post_stratified']:.3f} " + tex_newline,
        r"\bottomrule",
        r"\end{tabular}",
        r"\normalsize",
        r"\subsection*{Supplementary Table 3. Human reference-adjusted population estimates}",
        r"The automated population distribution is taken from all 2,800 benchmark groups. The conditional human-given-automated matrix is estimated from the design-weighted n=140 validation sample. The adjusted values are descriptive measurement-error corrections, not an assumed error-free gold standard. This reference-adjusted estimator differs by construction from the direct inverse-probability-weighted human rate in Supplementary Table 2.", r"\begin{tabular}{lrrr}", r"\toprule Label & Auto. (all 2,800 groups) & Reference-adjusted & 95\% CI " + tex_newline, r"\midrule"]
    adj = json.loads((HUMAN_OUT / "human_reference_adjusted_rates_v3.json").read_text())
    hvci = pd.read_csv(HUMAN_OUT / "human_validation_weighted_bootstrap_ci_v3.csv").set_index("metric")
    for lab in LABELS:
        row = hvci.loc[f"adjusted_{lab}"]
        lines.append(f"{esc(lab)} & {adj['automated_population_observed'][lab]:.3f} & {adj['reference_adjusted_from_population_automated'][lab]:.3f} & [{row.ci_low:.3f},{row.ci_high:.3f}] " + tex_newline)
    lines += [r"\bottomrule", r"\end{tabular}", r"\subsection*{Supplementary Table 4. Baseline model results}", r"The Poll. CI and Recog. CI columns are Wilson score intervals on each model's 100 benchmark items; they are not bootstrap intervals. Anti-poll. is the recognised count divided by recognised plus polluted counts.", r"\par\medskip", r"\scriptsize", r"\setlength{\tabcolsep}{2pt}", r"\begin{longtable}{>{\raggedright\arraybackslash}p{0.19\linewidth}rrrrrrrr}", r"\toprule Model & Rank & Poll. & Neutral & Recog. & Norm. & Anti-poll. & Poll. CI & Recog. CI " + tex_newline, r"\midrule", r"\endfirsthead", r"\toprule Model & Rank & Poll. & Neutral & Recog. & Norm. & Anti-poll. & Poll. CI & Recog. CI " + tex_newline, r"\midrule", r"\endhead"]
    base = pd.read_csv(TABLES / "baseline_results_v3.csv")
    for _, r in base.iterrows():
        lines.append(f"{esc(display_model.get(r.model, r.model))} & {int(r['rank'])} & {int(r.polluted)} & {int(r.neutral)} & {int(r.recognised)} & {r.normalised_score:.1f} & {r.antipollution_rate:.3f} & [{r.polluted_ci_low:.3f},{r.polluted_ci_high:.3f}] & [{r.recognised_ci_low:.3f},{r.recognised_ci_high:.3f}] " + tex_newline)
    lines += [r"\bottomrule", r"\end{longtable}", r"\subsection*{Supplementary Table 5. Paired safety-prompt effects}", r"\scriptsize", r"\setlength{\tabcolsep}{2pt}", r"\begin{longtable}{>{\raggedright\arraybackslash}p{0.19\linewidth}rrrrrrr}", r"\toprule Model & $\Delta$Norm & 95\% CI & $\Delta$Poll & 95\% CI & $p$ & $q$ & n \\", r"\midrule", r"\endfirsthead", r"\toprule Model & $\Delta$Norm & 95\% CI & $\Delta$Poll & 95\% CI & $p$ & $q$ & n \\", r"\midrule", r"\endhead"]
    for _, r in effects.sort_values("delta_norm", ascending=False).iterrows():
        lines.append(f"{esc(display_model.get(r.model, r.model))} & {r.delta_norm:+.2f} & [{r.delta_norm_ci_low:+.2f},{r.delta_norm_ci_high:+.2f}] & {100*r.delta_poll:+.2f} pp & [{100*r.delta_poll_ci_low:+.2f},{100*r.delta_poll_ci_high:+.2f}] & {r.wilcoxon_p:.4g} & {r.wilcoxon_q_bh:.4g} & {int(r.baseline_n)} " + tex_newline)
    citation_summary = json.loads((TABLES / "cohort_citation_summary_v3.json").read_text())
    lines += [r"\bottomrule", r"\end{longtable}", r"\subsection*{Supplementary Table 6. Item-level citation, temporal and theme analysis}", f"The top-100 cohort has {citation_summary['total_citations']:,} citations in total.", r"\begin{longtable}{rrrrr>{\raggedright\arraybackslash}p{0.26\linewidth}}", r"\toprule Item & Citations & Years & Poll. rate & Recog. rate & Theme \\", r"\midrule", r"\endfirsthead", r"\toprule Item & Citations & Years & Poll. rate & Recog. rate & Theme \\", r"\midrule", r"\endhead"]
    for _, r in item.sort_values("item_id").iterrows():
        lines.append(f"{int(r.item_id)} & {r.citations:.0f} & {r.years_since_retraction:.2f} & {r.polluted_rate:.3f} & {r.recognised_rate:.3f} & {esc(r.theme)} " + tex_newline)
    fdr_header = r"\toprule Test & Family & Effect & Estimate & Unit & Statistic & Value & raw $p$ & BH $q$ \\"
    lines += [r"\bottomrule", r"\end{longtable}", r"\subsection*{Supplementary Table 7. FDR family manifest}", r"\scriptsize", r"\setlength{\tabcolsep}{2pt}", r"\begin{longtable}{>{\raggedright\arraybackslash}p{0.16\linewidth}>{\raggedright\arraybackslash}p{0.09\linewidth}>{\raggedright\arraybackslash}p{0.15\linewidth}r>{\raggedright\arraybackslash}p{0.10\linewidth}>{\raggedright\arraybackslash}p{0.10\linewidth}rrr}", fdr_header, r"\midrule", r"\endfirsthead", fdr_header, r"\midrule", r"\endhead"]
    for _, r in fdr.iterrows():
        short_test = str(r.test).replace("prompt_effect_", "prompt:").replace("citation_spearman_", "citation:").replace("citation_tertile_trend_", "tertile:").replace("high_tertile_top10_vs_bottom10_", "high-tertile:").replace("temporal_spearman_", "temporal:").replace("temporal_before2021_vs_2021plus_", "temporal-group:").replace("ols_years_coefficient_", "OLS:")
        short_family = "intervention" if str(r.family).startswith("intervention") else "exploratory"
        lines.append(f"{esc(short_test)} & {esc(short_family)} & {esc(r.effect_name)} & {r.effect_estimate:.4g} & {esc(r.effect_unit)} & {esc(r.statistic_name)} & {r.statistic:.4g} & {r.raw_p:.4g} & {r.bh_q:.4g} " + tex_newline)
    calibrated_agreement = json.loads((HUMAN_OUT / "human_validation_calibrated_agreement_v3.json").read_text())
    human_agreement = json.loads((HUMAN_OUT / "human_validation_agreement_v3.json").read_text())
    lines += [r"\bottomrule", r"\end{longtable}", r"\subsection*{Supplementary Table 8. Human label confusion matrix}", f"The primary human label for A/B-agreement rows is the shared label; for the {human_agreement['adjudicated_n']} discrepant rows it is the adjudicator's label, assigned after Rater C reviewed both initial annotators' labels and written reasons while remaining blinded to model identity, prompt condition and the automated judge labels. This was a within-human consensus adjudication, not an independent third reading. Direct IPW agreement remains the primary estimate ({calibrated_agreement['direct_ipw_agreement_primary']:.3f}). The matrix is a sensitivity analysis post-stratified to the known automated-label margins (578 Polluted, 1,758 Neutral and 464 Recognised), with calibrated agreement {calibrated_agreement['poststratified_agreement_sensitivity']:.3f}.", r"\begin{tabular}{lrrr}", r"\toprule Automated label & Human Polluted & Human Neutral & Human Recognised \\", r"\midrule"]
    conf = pd.read_csv(HUMAN_OUT / "automated_human_confusion_calibrated_v3.csv", index_col=0)
    for idx, r in conf.iterrows():
        lines.append(f"{esc(idx)} & {r.get('Polluted',0):.1f} & {r.get('Neutral',0):.1f} & {r.get('Recognised',0):.1f} " + tex_newline)
    ab_conf = pd.read_csv(HUMAN_OUT / "human_human_confusion_unweighted_v3.csv", index_col=0)
    ab_diagonal = int(sum(ab_conf.loc[lab, lab] for lab in ["Polluted", "Neutral", "Recognised"] if lab in ab_conf.index))
    lines += [
        r"\bottomrule",
        r"\end{tabular}",
        r"\par\medskip",
        r"\small",
        f"The panel below reports the raw, unweighted cross-tabulation of the two annotators' own "
        f"pre-adjudication entries, so that the location of the human--human disagreements can be "
        f"inspected directly rather than only through $\\kappa$. Rows are Rater A and columns are Rater B. "
        f"The diagonal is {ab_diagonal} of 140. \\emph{{Unclear}} is a routing value that sends a row to "
        f"adjudication and is not a fourth outcome class, so it appears as a row only.",
        r"\par\medskip",
        r"\scriptsize",
        r"\begin{tabular}{lrrr}",
        r"\toprule Rater A $\downarrow$ / Rater B $\rightarrow$ & Polluted & Neutral & Recognised \\",
        r"\midrule",
    ]
    for idx, r in ab_conf.iterrows():
        lines.append(f"{esc(idx)} & {int(r.get('Polluted',0))} & {int(r.get('Neutral',0))} & {int(r.get('Recognised',0))} " + tex_newline)
    lines += [r"\bottomrule", r"\end{tabular}", r"\normalsize", r"\subsection*{Supplementary Table 9. Retraction-cause audit}", r"Each item has one mutually exclusive primary retraction-cause category. Republication status is recorded independently and is not treated as a cause. PREDIMED is classified under randomisation irregularities and separately recorded as republished.", r"\par\medskip", r"\begin{tabular}{lr}", r"\toprule Primary cause & Items \\", r"\midrule"]
    cause = pd.read_csv(TABLES / "retraction_cause_audit_v3.csv")
    cause_order = ["fabrication_or_manipulation", "misconduct_or_ethics", "other_or_unclassified", "duplication_or_overlap", "randomisation_irregularities"]
    cause_counts = cause.primary_retraction_cause.value_counts()
    for k in cause_order:
        lines.append(f"{esc(k)} & {int(cause_counts.get(k, 0))} " + tex_newline)
    lines += [
        r"\bottomrule",
        r"\end{tabular}",
        r"\par\medskip",
        r"Republication status is a separate variable from the primary cause, so it is tabulated separately here rather than inferred from the cause column.",
        r"\par\medskip",
        r"\begin{tabular}{lr}",
        r"\toprule Formal republication status & Items \\",
        r"\midrule",
    ]
    republication_order = ["Yes", "No", "Unknown"]
    republication_counts = cause.republication_status.value_counts()
    unexpected = sorted(set(republication_counts.index) - set(republication_order))
    if unexpected:
        raise ValueError(f"unexpected republication_status values: {unexpected}")
    for key in republication_order:
        lines.append(f"{esc(key)} & {int(republication_counts.get(key, 0))} " + tex_newline)
    lines += [
        r"\bottomrule",
        r"\end{tabular}",
        r"\clearpage",
        r"\normalsize",
        r"\subsection*{Supplementary Table 10. Normalised-score weighting and rank stability}",
        r"\small",
        r"For each scheme, let $w_P,w_N,w_R$ denote the raw loss weights assigned to Polluted, Neutral and Recognised labels. The reported 0--100 score is $100 \times [\max(w)-\overline{w}]/[\max(w)-\min(w)]$, so larger values are always more favourable. Scheme names such as \texttt{neutral\_0.50} refer to the raw Neutral loss weight, not to a mapped score of 50. The complete model-by-condition Polluted/Neutral/Recognised counts and rates are in \texttt{tables/summary\_by\_model\_condition\_v3.csv}; all scheme-specific scores are in \texttt{tables/normalised\_score\_sensitivity\_v3.csv}; and safety-minus-baseline effects under every scheme are in \texttt{tables/normalised\_score\_intervention\_sensitivity\_v3.csv}.",
        r"\par\medskip",
        r"\scriptsize",
        r"\begin{tabular}{lll}",
        r"\toprule Scheme & Raw losses $(P,N,R)$ & Mapped scores $(P,N,R)$ \\",
        r"\midrule",
    ]
    for scheme, weights in SENSITIVITY_SCHEMES.items():
        raw = tuple(weights[label] for label in LABELS)
        lo, hi = min(weights.values()), max(weights.values())
        mapped = tuple(100 * (hi - weights[label]) / (hi - lo) for label in LABELS)
        lines.append(
            f"{esc(scheme)} & ({raw[0]:g}, {raw[1]:g}, {raw[2]:g}) & "
            f"({mapped[0]:.1f}, {mapped[1]:.1f}, {mapped[2]:.1f}) " + tex_newline
        )
    lines += [
        r"\bottomrule",
        r"\end{tabular}",
        r"\par\medskip",
        r"\begin{tabular}{llr}",
        r"\toprule Scheme & Condition & Spearman rank correlation \\",
        r"\midrule",
    ]
    rank = pd.read_csv(TABLES / "normalised_score_rank_stability_v3.csv")
    for _, r in rank.iterrows():
        lines.append(f"{esc(r.scheme)} & {esc(r.condition)} & {r.spearman_rank_vs_default:.3f} " + tex_newline)
    lines += [r"\bottomrule", r"\end{tabular}", r"\subsection*{Supplementary Table 11. Self-preference analysis}", r"\scriptsize", r"\begin{tabular}{lrrrrrr}", r"\toprule Judge family & n & Own score & Other judges & $\Delta$ & $p$ (Wilcoxon) & $q$ \\", r"\midrule"]
    self_pref = pd.read_csv(TABLES / "self_preference_v3.csv")

    def fmt_p(value: float) -> str:
        # A Benjamini--Hochberg q value is capped at 1, and a bare "1" reads as a count rather than
        # a probability, so report the conventional bound instead and keep the main text identical.
        return r"$>$0.999" if float(value) >= 0.9995 else f"{float(value):.4g}"

    for _, r in self_pref.iterrows(): lines.append(f"{esc(r.judge_family)} & {int(r.n_observations)} & {r.mean_own_family_score:.3f} & {r.mean_other_judges_score:.3f} & {r.delta_own_minus_other:+.3f} & {fmt_p(r.wilcoxon_p)} & {fmt_p(r.wilcoxon_q_bh)} " + tex_newline)
    secondary = pd.read_csv(HUMAN_OUT / "secondary_field_agreement_v3.csv")
    lines += [
        r"\bottomrule",
        r"\end{tabular}",
        r"\subsection*{Supplementary Table 12. Human secondary-field agreement and rater distributions}",
        r"\small",
        r"Two of the four secondary fields are scoped by the frozen rubric rather than asked of every "
        r"response: \texttt{neutral\_subtype} is answered only when the rater's own primary label is "
        r"Neutral, and \texttt{conclusion\_overlap} only when the rater did not find the target article "
        r"cited or identifiably relied upon. Outside that scope both raters enter \emph{Not applicable}, "
        r"so those cells agree by construction. The whole-sample agreement column therefore contains "
        r"deterministic matches and is not a reliability estimate on its own; the applicable-row "
        r"denominator, on which both raters actually recorded a value, is given alongside it. "
        r"Permitted response options that neither rater ever selected are retained below with a zero "
        r"count so that the null result stays visible. "
        r"For the two scoped fields the three columns do not sum to 140, because a row is counted as "
        r"applicable only when \emph{both} raters recorded a value. Rater A returned 60 Neutral primary "
        r"labels and Rater B returned 63, of which 57 coincide, so 74 rows are out of scope for both "
        r"raters, 57 are in scope for both, and the remaining 9 are in scope for exactly one rater "
        r"(3 for A only and 6 for B only). Those 9 rows are counted as disagreements in the "
        r"whole-sample column and excluded from the applicable-row denominator. The two scoped fields "
        r"share the same denominators because, in this subsample, the condition that the rater did not "
        r"find the target article cited or identifiably relied upon coincided exactly with that rater "
        r"assigning a Neutral primary label; the identical counts are therefore a property of the data "
        r"rather than a duplicated row.",
        r"\par\medskip",
        r"\scriptsize",
        r"\begin{tabular}{lrrrr}",
        r"\toprule Field & Whole-sample agreement & Both not applicable & Applicable rows & Applicable agreement \\",
        r"\midrule",
    ]
    for _, summary_row in secondary.iterrows():
        applicable_n = int(summary_row.applicable_both_n)
        applicable_rate = (
            f"{int(summary_row.applicable_agreement_n)}/{applicable_n} ({summary_row.applicable_agreement_rate:.3f})"
            if applicable_n
            else "not estimable"
        )
        lines.append(
            f"{esc(summary_row.field)} & {int(summary_row.ab_agreement_n)}/{int(summary_row.n)} "
            f"({summary_row.ab_agreement_rate:.3f}) & {int(summary_row.both_not_applicable_n)} & "
            f"{applicable_n} & {applicable_rate} " + tex_newline
        )
    lines += [
        r"\bottomrule",
        r"\end{tabular}",
        r"\par\medskip",
        r"\begin{longtable}{>{\raggedright\arraybackslash}p{0.22\linewidth}>{\raggedright\arraybackslash}p{0.38\linewidth}rr}",
        r"\toprule Field & Category & Rater A n & Rater B n \\",
        r"\midrule",
        r"\endfirsthead",
        r"\toprule Field & Category & Rater A n & Rater B n \\",
        r"\midrule",
        r"\endhead",
    ]
    for _, summary_row in secondary.iterrows():
        distribution = pd.read_csv(HUMAN_OUT / f"secondary_{summary_row.field}_rater_distributions_v3.csv")
        for _, distribution_row in distribution.iterrows():
            lines.append(
                f"{esc(summary_row.field)} & {esc(distribution_row.value)} & "
                f"{int(distribution_row.a_n)} & {int(distribution_row.b_n)} " + tex_newline
            )
    lines += [r"\bottomrule", r"\end{longtable}", r"\end{document}"]
    generated = "\n".join(lines) + "\n"
    marker = r"\subsection*{Analysis provenance}"
    generated_tables = generated[generated.index(marker):generated.rindex(r"\end{document}")]
    (OUT / "supplementary_materials.tex").write_text(
        assemble_supplement(generated_tables), encoding="utf-8"
    )


def main() -> None:
    ensure_dirs()
    write_input_manifest()
    judgments, majority, inventory = load_benchmark()
    meta = load_item_metadata(majority)
    citation_summary = make_citation_summary(meta)
    summary, baseline = make_summary_tables(majority)
    effects, pooled = make_prompt_effects(majority)
    judge_agreement = make_judge_agreement(judgments, majority)
    make_sensitivity(majority)
    item = make_theme_and_item_tables(majority, meta)
    fdr = make_citation_temporal_fdr(item, majority)
    self_pref = make_self_preference(judgments)
    # Add the 14-model intervention family then BH-correct the exploratory family.
    fdr_intervention = effects[["model", "delta_norm", "wilcoxon_w", "wilcoxon_p", "wilcoxon_q_bh"]].copy()
    fdr_intervention["test"] = "prompt_effect_" + fdr_intervention.model.astype(str)
    fdr_intervention["family"] = "intervention_14_model_paired"
    fdr_intervention["method"] = "Wilcoxon paired item scores"
    fdr_intervention["sample_unit"] = "paired benchmark item within model"
    fdr_intervention["direction"] = "two-sided"
    fdr_intervention["effect_name"] = "safety-minus-baseline normalised score"
    fdr_intervention["effect_estimate"] = fdr_intervention.pop("delta_norm")
    fdr_intervention["effect_unit"] = "points"
    fdr_intervention["statistic_name"] = "Wilcoxon W"
    fdr_intervention["statistic"] = fdr_intervention.pop("wilcoxon_w")
    fdr_intervention = fdr_intervention.rename(columns={"wilcoxon_p": "raw_p", "wilcoxon_q_bh": "bh_q"})
    fdr_intervention["bh_rank"] = fdr_intervention["raw_p"].rank(method="first").astype(int)
    fdr_intervention = fdr_intervention[["test", "family", "method", "sample_unit", "direction", "effect_name", "effect_estimate", "effect_unit", "statistic_name", "statistic", "raw_p", "bh_rank", "bh_q"]]
    fdr["bh_q"] = np.nan
    mask = fdr.family == "exploratory_citation_temporal_subgroup_regression"
    fdr.loc[mask, "bh_q"] = bh_qvalues(fdr.loc[mask, "raw_p"].to_numpy())
    fdr["bh_rank"] = np.nan
    fdr.loc[mask, "bh_rank"] = fdr.loc[mask, "raw_p"].rank(method="first").astype(int)
    fdr = fdr[["test", "family", "method", "sample_unit", "direction", "effect_name", "effect_estimate", "effect_unit", "statistic_name", "statistic", "raw_p", "bh_rank", "bh_q", "note"]]
    fdr_all = pd.concat([fdr_intervention, fdr], ignore_index=True)
    fdr_all.to_csv(TABLES / "fdr_manifest_v3.csv", index=False)
    # Cause audit: keep primary cause and republication as separate variables.
    old = pd.read_csv(CAUSE_AUDIT_PATH)
    mapping = {
        "fabrication_or_manipulation": "fabrication_or_manipulation",
        "misconduct_or_ethics": "misconduct_or_ethics",
        "randomisation_irregularities": "randomisation_irregularities",
        "retracted_and_republished": "other_or_unclassified",
        "duplication_or_overlap": "duplication_or_overlap",
        "other_or_unclassified": "other_or_unclassified",
    }
    old["primary_retraction_cause"] = old.cause_category.map(mapping).fillna("other_or_unclassified")
    republish_by_item = (
        meta.set_index("item_id")["Republish"]
        .fillna("Unknown")
        .astype(str)
        .replace({"": "Unknown", "nan": "Unknown", "Not found": "Unknown"})
    )
    old["republication_status"] = old.item_id.map(republish_by_item).fillna("Unknown")
    old["post_retraction_reanalysis"] = "No"
    old["replacement_doi"] = ""
    overrides = pd.read_csv(CAUSE_OVERRIDE_PATH).set_index("item_id")
    for item_id, row in overrides.iterrows():
        mask = old.item_id.eq(int(item_id))
        if int(mask.sum()) != 1:
            raise ValueError(f"cause override item {item_id} did not match exactly one row")
        for column in (
            "primary_retraction_cause",
            "republication_status",
            "post_retraction_reanalysis",
            "replacement_doi",
        ):
            if column in row.index and pd.notna(row[column]):
                old.loc[mask, column] = row[column]
    old["strategy_category"] = old["primary_retraction_cause"]
    old.to_csv(TABLES / "retraction_cause_audit_v3.csv", index=False)
    human = make_human_validation(majority)
    generate_figures(majority, item)
    write_supplementary(majority, summary, effects, item, human, fdr_all, judge_agreement)
    # Machine-readable text fragments for manuscript replacement.
    pooled_json = json.loads((TABLES / "pooled_prompt_effect_ci_v3.json").read_text())
    pbase = pd.read_csv(TABLES / "pooled_results_v3.csv")
    text = {
        "baseline_pooled": score_summary(majority.loc[majority.condition == "baseline", "majority_score"].to_numpy()),
        "safety_pooled": score_summary(majority.loc[majority.condition == "safety", "majority_score"].to_numpy()),
        "baseline_table": baseline.to_dict("records"), "prompt_effects": effects.to_dict("records"),
        "pooled_prompt_effect_ci": pooled_json,
        "human_weighted_summary": pd.read_csv(HUMAN_OUT / "human_validation_weighted_summary_v3.csv").to_dict("records"),
        "human_bootstrap_ci": pd.read_csv(HUMAN_OUT / "human_validation_weighted_bootstrap_ci_v3.csv").to_dict("records"),
        "top_polluted_items": item.sort_values("polluted_count", ascending=False).head(20).to_dict("records"),
        "top_recognised_items": item.sort_values("recognised_count", ascending=False).head(20).to_dict("records"),
        "judge_agreement": judge_agreement,
        "cohort_citation_summary": citation_summary,
        "fdr": fdr_all.to_dict("records"),
        "self_preference": self_pref.to_dict("records"),
    }
    write_json(TEXT / "results_fragments_v3.json", text)

    supplement_text = (OUT / "supplementary_materials.tex").read_text(encoding="utf-8")
    supplement_tables = len(re.findall(r"\\subsection\*\{Supplementary Table \d+\.", supplement_text))
    output_files = sorted(
        p for p in OUT.rglob("*")
        if p.is_file()
        and p.name != "analysis_manifest_v3.json"
        and ".pytest_cache" not in p.parts
        and "__pycache__" not in p.parts
        and p.name != ".DS_Store"
    )
    write_json(OUT / "analysis_manifest_v3.json", {
        **inventory,
        "analysis_date": str(ANALYSIS_DATE.date()),
        "seed": SEED,
        "bootstrap_iterations": BOOTSTRAP,
        "human_sample_n": len(human),
        "human_adjudicated_n": int(human.adjudicated.sum()),
        "human_ab_agreement_rate": float(human.ab_agree.mean()),
        "human_auto_agreement_unweighted": float(human.human_auto_agree.mean()),
        "item_metadata_title_mismatches": int((~meta.title_matches_judgment).sum()),
        "pooled_effect": pooled_json,
        "supplementary_table_count": supplement_tables,
        "input_manifest_sha256": sha256_file(OUT / "input_manifest_v3.json"),
        "analysis_script_sha256": sha256_file(Path(__file__)),
        "test_file_sha256": sha256_file(OUT / "tests/test_analysis_outputs.py"),
        "outputs": [str(path.relative_to(OUT)) for path in output_files],
        "analysis_outputs_verified": supplement_tables == EXPECTED_SUPPLEMENTARY_TABLES,
        "document_compile_verified": False,
    })
    print(json.dumps({"ok": True, "output": str(OUT), "groups": len(majority), "human_n": len(human), "human_adjudicated": int(human.adjudicated.sum()), "baseline_polluted": text["baseline_pooled"]["polluted_rate"], "safety_polluted": text["safety_pooled"]["polluted_rate"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
