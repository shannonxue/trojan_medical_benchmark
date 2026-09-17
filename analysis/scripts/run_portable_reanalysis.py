#!/usr/bin/env python3
"""Run the V3 reanalysis from a self-contained release bundle."""
from __future__ import annotations

import argparse
from pathlib import Path

import analyze_v3


def configure_analysis_for_bundle(module, bundle_root: Path) -> None:
    root = Path(bundle_root).resolve()
    module.PROJECT = root
    module.V3 = root
    module.OUT = root / "analysis"
    module.INPUT = module.OUT / "inputs"
    module.TABLES = module.OUT / "tables"
    module.FIGURES = module.OUT / "figures"
    module.HUMAN_OUT = module.OUT / "human_validation"
    module.TEXT = module.OUT / "text_fragments"
    module.TEMPLATES = module.OUT / "templates"
    module.JUDGMENTS_PATH = root / "data/judgments_repaired.csv"
    module.MASTER_PATH = root / "human_validation/n140_master_unblinded_postpatch_v3.xlsx"
    module.RATER_A_PATH = root / "human_validation/n140_rater_A_blinded.xlsx"
    module.RATER_B_PATH = root / "human_validation/n140_rater_B_blinded.xlsx"
    module.ADJUDICATION_PATH = root / "human_validation/adjudication_summary_13_rows.xlsx"
    module.METADATA_PATH = root / "analysis/inputs/retractions_selected_100.csv"
    module.CAUSE_AUDIT_PATH = root / "analysis/inputs/retraction_cause_audit_source.csv"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--bundle-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Root of the extracted V3 release bundle",
    )
    args = parser.parse_args()
    configure_analysis_for_bundle(analyze_v3, args.bundle_root)
    analyze_v3.main()


if __name__ == "__main__":
    main()
