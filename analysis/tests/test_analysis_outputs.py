from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT
TABLES = OUT / "tables"
HUMAN = OUT / "human_validation"
sys.path.insert(0, str(ROOT / "scripts"))
import analyze_v3 as analysis
import run_portable_reanalysis as portable


def test_working_copy_analysis_paths_do_not_target_frozen_v3():
    assert analysis.OUT == ROOT
    assert analysis.V3 == ROOT.parent


def test_supplement_layout_and_case_order_survive_regeneration(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis, "OUT", tmp_path)
    analysis.write_supplementary(
        pd.read_csv(TABLES / "majority_votes_v3.csv"),
        pd.read_csv(TABLES / "summary_by_model_condition_v3.csv"),
        pd.read_csv(TABLES / "prompt_effects_v3.csv"),
        pd.read_csv(TABLES / "item_level_baseline_v3.csv"),
        pd.DataFrame(),
        pd.read_csv(TABLES / "fdr_manifest_v3.csv"),
        json.loads((TABLES / "judge_agreement_v3.json").read_text()),
    )
    generated = (tmp_path / "supplementary_materials.tex").read_text()
    assert generated == (ROOT / "supplementary_materials.tex").read_text()
    heading = r"\subsection*{Supplementary Table 10."
    before, table10 = generated.split(heading, 1)
    assert before.rstrip().endswith(r"\clearpage" + "\n" + r"\normalsize")
    table10 = table10.split(r"\subsection*{Supplementary Table 11.", 1)[0]
    assert r"\par\medskip" + "\n" + r"\scriptsize" + "\n" + r"\begin{tabular}{lll}" in table10
    table15 = generated.split("Supplementary Table 15.", 1)[1].split("Supplementary Table 16.", 1)[0]
    assert "GPT-5.5 / Claude Opus 4.7 / Gemini 3.1 Pro" in table15
    assert "differs from the order in Supplementary Table 14" in table15


def test_benchmark_shape_and_primary_counts():
    majority = pd.read_csv(TABLES / "majority_votes_v3.csv")
    assert len(majority) == 2800
    assert majority[["model", "condition", "item_id"]].drop_duplicates().shape[0] == 2800
    assert majority.groupby(["model", "condition", "item_id"]).size().max() == 1
    assert majority.model.nunique() == 14
    assert set(majority.condition) == {"baseline", "safety"}
    base = majority[majority.condition == "baseline"]
    safe = majority[majority.condition == "safety"]
    assert (base.majority_label == "Polluted").sum() == 400
    assert (base.majority_label == "Neutral").sum() == 927
    assert (base.majority_label == "Recognised").sum() == 73
    assert (safe.majority_label == "Polluted").sum() == 178
    assert (safe.majority_label == "Neutral").sum() == 831
    assert (safe.majority_label == "Recognised").sum() == 391


def test_per_model_proportion_cis_use_wilson_but_intervention_cis_remain_bootstrap():
    baseline = pd.read_csv(TABLES / "baseline_results_v3.csv")
    zero_recognised = baseline.loc[baseline.recognised.eq(0)]

    assert baseline.proportion_ci_method.eq("two-sided Wilson").all()
    assert zero_recognised.recognised_ci_low.eq(0).all()
    assert np.allclose(zero_recognised.recognised_ci_high, 0.03699349820698568)

    effects = pd.read_csv(TABLES / "prompt_effects_v3.csv")
    assert effects.ci_method.eq("paired item bootstrap").all()


def test_locked_theme_mapping_corrects_known_items_and_regenerates_dependents():
    assert set(analysis.LOCKED_THEME_BY_ITEM) == set(range(1, 101))
    assert analysis.LOCKED_THEME_BY_ITEM[62] == "Cardiovascular & hypertension"
    assert analysis.LOCKED_THEME_BY_ITEM[33] == "Other"

    assignments = pd.read_csv(TABLES / "item_theme_assignments_v3.csv").set_index("item_id")
    assert assignments.loc[62, "theme"] == "Cardiovascular & hypertension"
    assert assignments.loc[33, "theme"] == "Other"
    assert assignments.theme_assignment_method.eq("locked 100-item mapping").all()

    themes = pd.read_csv(TABLES / "theme_summary_v3.csv")
    assert themes["items"].sum() == 100
    fdr = pd.read_csv(TABLES / "fdr_manifest_v3.csv")
    ols = fdr[fdr.test.str.startswith("ols_years_coefficient_")]
    assert len(ols) == 2
    assert ols.method.str.contains("locked theme fixed effects").all()
    assert ols.bh_q.notna().all()


def test_human_resolution_and_design_weight():
    h = pd.read_csv(HUMAN / "human_label_resolution_v3.csv")
    assert len(h) == 140
    assert h.sample_id.nunique() == 140
    assert int(h.adjudicated.sum()) == 13
    assert int(h.ab_agree.sum()) == 127
    assert set(h.human_label_final) <= {"Polluted", "Neutral", "Recognised"}
    assert abs(h.design_weight.sum() - 2800) < 1e-6
    agreement = json.loads((HUMAN / "human_validation_agreement_v3.json").read_text())
    assert agreement["ab_agreement_n"] == 127
    assert 0.85 < agreement["cohen_kappa_ab"] < 0.87
    assert agreement["cohen_kappa_ab_ci_low"] <= agreement["cohen_kappa_ab"]
    assert agreement["cohen_kappa_ab"] <= agreement["cohen_kappa_ab_ci_high"]


def test_human_bootstrap_and_reference_adjustment_are_finite():
    ci = pd.read_csv(HUMAN / "human_validation_weighted_bootstrap_ci_v3.csv")
    assert not ci[["estimate", "ci_low", "ci_high"]].isna().any().any()
    assert (ci.ci_low <= ci.estimate).all()
    assert (ci.estimate <= ci.ci_high).all()
    ref = json.loads((HUMAN / "human_reference_adjusted_rates_v3.json").read_text())
    assert abs(sum(ref["automated_population_observed"].values()) - 1) < 1e-9
    assert abs(sum(ref["reference_adjusted_from_population_automated"].values()) - 1) < 1e-9


def test_poststratified_confusion_uses_known_margins_and_keeps_direct_ipw_primary():
    h = pd.read_csv(HUMAN / "human_label_resolution_v3.csv")
    assert len(h) == 140
    assert h.stratum.value_counts().to_dict() == {
        "unanimous_neutral": 50,
        "any_disagreement": 35,
        "unanimous_polluted": 30,
        "unanimous_recognised": 25,
    }

    calibrated = pd.read_csv(
        HUMAN / "automated_human_confusion_calibrated_v3.csv", index_col=0
    ).reindex(index=analysis.LABELS, columns=analysis.LABELS)
    expected_margins = pd.Series(
        {"Polluted": 578.0, "Neutral": 1758.0, "Recognised": 464.0}
    )
    assert np.allclose(calibrated.sum(axis=1), expected_margins)

    sensitivity = json.loads(
        (HUMAN / "human_validation_calibrated_agreement_v3.json").read_text()
    )
    assert sensitivity["n_validation"] == 140
    assert sensitivity["primary_estimator"] == "direct IPW"
    assert sensitivity["direct_ipw_agreement_primary"] == pytest.approx(0.9572217086834733)
    assert sensitivity["poststratified_agreement_sensitivity"] == pytest.approx(
        np.trace(calibrated.to_numpy()) / 2800
    )


def test_fdr_manifest_and_outputs():
    fdr = pd.read_csv(TABLES / "fdr_manifest_v3.csv")
    assert len(fdr) == 14 + 13
    assert fdr.raw_p.notna().all()
    assert fdr.bh_q.notna().all()
    assert fdr.bh_rank.notna().all()
    assert fdr.sample_unit.notna().all()
    assert fdr.direction.eq("two-sided").all()
    assert set(fdr.family) == {"intervention_14_model_paired", "exploratory_citation_temporal_subgroup_regression"}
    required = {
        "effect_name", "effect_estimate", "effect_unit", "statistic_name", "statistic"
    }
    assert required.issubset(fdr.columns)
    assert "estimate" not in fdr.columns
    assert fdr[list(required)].notna().all().all()

    intervention = fdr[fdr.family.eq("intervention_14_model_paired")]
    assert intervention.statistic_name.eq("Wilcoxon W").all()
    assert intervention.effect_name.eq("safety-minus-baseline normalised score").all()
    assert intervention.effect_unit.eq("points").all()

    top_recognised = fdr.loc[
        fdr.test.eq("high_tertile_top10_vs_bottom10_recognised_rate")
    ].iloc[0]
    assert top_recognised.statistic_name == "Mann-Whitney U_top"
    assert top_recognised.statistic == pytest.approx(77.5)

    spearman = fdr[fdr.method.str.contains("Spearman")]
    assert spearman.statistic_name.eq("Spearman rho").all()
    ols = fdr[fdr.test.str.startswith("ols_years_coefficient_")]
    assert ols.effect_name.eq("OLS beta for years_since_retraction").all()
    assert ols.statistic_name.eq("OLS t").all()

    assert (TABLES / "normalised_score_sensitivity_v3.csv").exists()
    assert (TABLES / "normalised_score_rank_stability_v3.csv").exists()
    assert (TABLES / "normalised_score_intervention_sensitivity_v3.csv").exists()
    supplement = (OUT / "supplementary_materials.tex").read_text()
    table10 = supplement.split("Supplementary Table 10.", 1)[1].split(
        "Supplementary Table 11.", 1
    )[0]
    assert "Raw losses $(P,N,R)$" in table10
    assert "Mapped scores $(P,N,R)$" in table10
    assert "(1, 0, -1) & (0.0, 50.0, 100.0)" in table10
    assert "(1, 0.5, -1) & (0.0, 25.0, 100.0)" in table10
    assert r"tables/summary\_by\_model\_condition\_v3.csv" in table10
    assert r"tables/normalised\_score\_intervention\_sensitivity\_v3.csv" in table10
    complete = pd.read_csv(TABLES / "summary_by_model_condition_v3.csv")
    assert len(complete) == 28
    assert {"polluted", "neutral", "recognised", "polluted_rate", "neutral_rate", "recognised_rate"}.issubset(complete.columns)
    table7 = supplement.split("Supplementary Table 7.", 1)[1].split(
        "Supplementary Table 8.", 1
    )[0]
    assert "Effect & Estimate & Unit & Statistic & Value" in table7
    for table_number in range(1, 17):
        assert f"Supplementary Table {table_number}." in supplement
    assert "Supplementary Table 16. Illustrative onboarding checklist" in supplement
    assert "Supplementary Table 17." not in supplement
    # Cross-references (for example Table 15 referring to Table 14) are not tables.
    assert supplement.count(r"\subsection*{Supplementary Table ") == 16
    assert (OUT / "supplementary_materials.tex").exists()


def test_supplement_table_12_renders_complete_secondary_field_distributions():
    supplement = (OUT / "supplementary_materials.tex").read_text()
    table12 = supplement.split("Supplementary Table 12.", 1)[1].split(
        "Supplementary Table 13.", 1
    )[0]

    for field in ["conclusion_overlap", "neutral_subtype", "republication_handling", "confidence"]:
        distribution = pd.read_csv(HUMAN / f"secondary_{field}_rater_distributions_v3.csv")
        rendered_field = field.replace("_", r"\_")
        for row in distribution.itertuples():
            rendered_value = str(row.value).replace("&", r"\&").replace("_", r"\_")
            assert f"{rendered_field} & {rendered_value} & {row.a_n} & {row.b_n}" in table12

    assert r"neutral\_subtype & Valid alternative evidence & 49 & 57" in table12
    assert r"neutral\_subtype & Appropriate avoidance/abstention & 5 & 2" in table12
    assert r"neutral\_subtype & No substantive evidence & 3 & 3" in table12
    assert r"neutral\_subtype & Unverifiable/fabricated citation & 3 & 1" in table12


def test_cohort_citation_summary_includes_top100_total():
    summary = json.loads((TABLES / "cohort_citation_summary_v3.json").read_text())
    assert summary["cohort"] == "top-100 most-cited retracted RCTs"
    assert summary["item_count"] == 100
    assert summary["total_citations"] == 24_803

    fragments = json.loads((OUT / "text_fragments/results_fragments_v3.json").read_text())
    assert fragments["cohort_citation_summary"] == summary


def test_fleiss_kappa_is_formatted_to_three_decimals_in_tex():
    supplement = (OUT / "supplementary_materials.tex").read_text()
    assert "fleiss\\_kappa & 0.910 \\\\" in supplement
    assert "0.910036" not in supplement


def test_generated_text_exposes_item_cluster_and_two_way_pooled_cis():
    fragments = json.loads((OUT / "text_fragments/results_fragments_v3.json").read_text())
    pooled = json.loads((TABLES / "pooled_prompt_effect_ci_v3.json").read_text())

    assert fragments["pooled_prompt_effect_ci"] == pooled
    assert set(fragments["pooled_prompt_effect_ci"]) >= {
        "item_cluster", "two_way_model_item", "point_delta_norm", "point_delta_poll"
    }
    assert set(fragments["pooled_prompt_effect_ci"]["item_cluster"]) >= {
        "delta_norm_ci_low", "delta_norm_ci_high", "delta_poll_ci_low", "delta_poll_ci_high"
    }
    assert set(fragments["pooled_prompt_effect_ci"]["two_way_model_item"]) >= {
        "two_way_delta_norm_ci_low", "two_way_delta_norm_ci_high",
        "two_way_delta_poll_ci_low", "two_way_delta_poll_ci_high",
    }


def test_retraction_cause_overrides_are_separate_complete_and_authoritative():
    audit = pd.read_csv(TABLES / "retraction_cause_audit_v3.csv")
    assert len(audit) == 100
    assert audit.item_id.nunique() == 100
    assert {"primary_retraction_cause", "republication_status"}.issubset(audit.columns)
    assert audit[["primary_retraction_cause", "republication_status"]].notna().all().all()

    item32 = audit.loc[audit.item_id.eq(32)].iloc[0]
    assert item32.primary_retraction_cause == "other_or_unclassified"
    assert item32.republication_status == "No"
    assert item32.post_retraction_reanalysis == "Yes"
    assert item32.replacement_doi == "10.1007/s00125-018-4628-9"

    item28 = audit.loc[audit.item_id.eq(28)].iloc[0]
    assert item28.republication_status == "Yes"

    predimed = audit.loc[audit.item_id.eq(73)].iloc[0]
    assert "Mediterranean diet" in predimed.study_title
    assert predimed.primary_retraction_cause == "randomisation_irregularities"
    assert predimed.republication_status == "Yes"


def test_input_manifest_has_hashes_and_runtime_versions():
    manifest_path = OUT / "input_manifest_v3.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    if analysis.IS_RELEASE_BUNDLE:
        assert manifest["manifest_role"] == "portable_release_inputs"
        assert manifest["path_base"] == "release_candidate"
        assert "historical only" in manifest["historical_record_status"]
    else:
        assert manifest["manifest_role"] == "current_working_copy_inputs"
        assert manifest["path_base"] == "repository_root"
        assert "historical location labels" in manifest["historical_record_status"]
    historical_path = ROOT.parent / manifest["historical_record_path"]
    assert historical_path.is_file()
    historical = json.loads(historical_path.read_text())
    assert historical["record_role"] == "historical_input_manifest_snapshot"
    assert historical["status"] == "superseded_by_input_manifest_v3.json"
    assert all(not entry["path"].startswith("provenance://v3-source/") for entry in manifest["inputs"])
    assert manifest["analysis_seed"] == 20260809
    assert manifest["bootstrap_iterations"] == 10000
    assert manifest["inputs"]
    assert all(entry["sha256"] and entry["bytes"] > 0 for entry in manifest["inputs"])
    assert manifest["software_versions"]["python"]
    assert manifest["software_versions"]["pandas"]

    analysis_manifest = json.loads((OUT / "analysis_manifest_v3.json").read_text())
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    assert analysis_manifest["input_manifest_sha256"] == sha(manifest_path)
    assert analysis_manifest["analysis_script_sha256"] == sha(OUT / "scripts/analyze_v3.py")
    assert analysis_manifest["test_file_sha256"] == sha(OUT / "tests/test_analysis_outputs.py")


def test_pooled_bootstrap_resamples_items_as_clusters(monkeypatch):
    """A pooled draw must retain all model columns within each sampled item."""

    class FixedRng:
        def integers(self, low, high, size):
            assert low == 0
            assert high == 2
            assert size == (2, 2)
            return np.array([[0, 0], [1, 1]])

    monkeypatch.setattr(analysis, "BOOTSTRAP", 2)
    baseline = np.array([[1, 1, 1], [0, 0, 0]], dtype=float)
    safety = np.zeros_like(baseline)
    ci = analysis.paired_item_bootstrap(baseline, safety, FixedRng())

    assert ci["delta_poll_ci_low"] == pytest.approx(-0.975)
    assert ci["delta_poll_ci_high"] == pytest.approx(-0.025)
    assert ci["delta_norm_ci_low"] == pytest.approx(1.25)
    assert ci["delta_norm_ci_high"] == pytest.approx(48.75)


def test_human_design_weights_match_current_population_cells():
    majority = pd.read_csv(TABLES / "majority_votes_v3.csv")
    h = pd.read_csv(HUMAN / "human_label_resolution_v3.csv")
    majority["sampling_stratum"] = np.where(
        majority["stratum"].eq("unanimous"),
        "unanimous_" + majority["majority_label"].str.lower(),
        "any_disagreement",
    )
    population_n = majority.groupby(["sampling_stratum", "condition"]).size()
    sample_n = h.groupby(["stratum", "condition"]).size()
    expected = np.array([
        population_n[(row.stratum, row.condition)] / sample_n[(row.stratum, row.condition)]
        for row in h.itertuples()
    ])
    assert np.allclose(h["design_weight"].to_numpy(float), expected)
    corrected_workbook = HUMAN / "n140_master_unblinded_postpatch_v3.xlsx"
    assert corrected_workbook.exists()
    corrected = pd.read_excel(corrected_workbook, sheet_name="sample_manifest")
    assert set(corrected["sample_id"]) == set(h["sample_id"])
    assert np.allclose(corrected["design_weight"].to_numpy(float), expected)


def test_supplement_assembly_preserves_methods_and_late_tables():
    rendered = analysis.assemble_supplement("GENERATED-TABLES-1-12")
    assert "Supplementary Methods M1--M2" in rendered
    assert "Supplementary Methods M4" in rendered
    assert "GENERATED-TABLES-1-12" in rendered
    assert "Supplementary Table 13" in rendered
    assert "Supplementary Table 16" in rendered
    assert rendered.count("\\end{document}") == 1


def test_portable_release_configuration_uses_bundle_paths(tmp_path):
    from types import SimpleNamespace

    bundle = tmp_path / "release"
    configured = SimpleNamespace()
    portable.configure_analysis_for_bundle(configured, bundle)
    assert configured.PROJECT == bundle
    assert configured.V3 == bundle
    assert configured.OUT == bundle / "analysis"
    assert configured.JUDGMENTS_PATH == bundle / "data/judgments_repaired.csv"
    assert configured.MASTER_PATH == bundle / "human_validation/n140_master_unblinded_postpatch_v3.xlsx"
    assert configured.METADATA_PATH == bundle / "analysis/inputs/retractions_selected_100.csv"


def test_metadata_loader_allows_source_already_in_output_directory(tmp_path, monkeypatch):
    inputs = tmp_path / "inputs"
    tables = tmp_path / "tables"
    inputs.mkdir()
    tables.mkdir()
    metadata = pd.DataFrame({
        "Title_New": [f"Title {i}" for i in range(1, 101)],
        "Citations": list(range(1, 101)),
        "RetractionDate": ["2020-01-01"] * 100,
        "Date of Publish": ["2010-01-01"] * 100,
        "Condition (disease)": ["Other"] * 100,
    })
    metadata_path = inputs / "retractions_selected_100.csv"
    metadata.to_csv(metadata_path, index=False)
    majority = pd.DataFrame({
        "item_id": list(range(1, 101)),
        "study_title": [f"Title {i}" for i in range(1, 101)],
    })
    monkeypatch.setattr(analysis, "INPUT", inputs)
    monkeypatch.setattr(analysis, "TABLES", tables)
    monkeypatch.setattr(analysis, "METADATA_PATH", metadata_path)
    loaded = analysis.load_item_metadata(majority)
    assert len(loaded) == 100
