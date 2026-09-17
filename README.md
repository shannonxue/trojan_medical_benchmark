# Retracted-Evidence Resistance Benchmark — V3 release bundle

Materials supporting the study "A retracted-evidence resistance benchmark for medical large language models and safety-prompt mitigation".

Openly available at https://github.com/shannonxue/trojan_medical_benchmark under a CC BY 4.0 licence.

## Large files are stored with Git LFS

Some binary artifacts in this repository are tracked with [Git LFS](https://git-lfs.com) rather than stored directly in Git. The tracked patterns are declared in `.gitattributes`:

```
*.pdf
*.xlsx
*.zip
```

In practice this covers the human-validation workbooks (`human_validation/*.xlsx`, mirrored under `analysis/human_validation/`) and the PDF figures under `figures/`.

- **Downloading individual files from the GitHub web interface works normally** and requires no extra tooling; GitHub resolves LFS objects transparently.
- **`git clone` requires Git LFS to be installed first.** Without it, the files listed above are checked out as small text pointer stubs rather than real documents, which is easy to mistake for corrupted or empty files.

To clone with the real file contents:

```bash
# install once, e.g. `brew install git-lfs`, `apt install git-lfs`, or see https://git-lfs.com
git lfs install
git clone https://github.com/shannonxue/trojan_medical_benchmark.git
```

If you have already cloned the repository without Git LFS, run:

```bash
git lfs install
git lfs pull
```

To confirm which files are LFS-tracked in your checkout, run `git lfs ls-files`. All plain-text artifacts — the judgment layer, majority-vote labels, item metadata, answer JSON files, analysis tables, provenance manifests, scripts and LaTeX sources — are stored directly in Git and need no LFS.

## Reproduce the V3 analysis

```bash
uv run --no-project --with-requirements analysis/requirements-analysis.txt -- \
  python analysis/scripts/analyze_v3.py
```

The analysis script auto-detects the bundle layout and reads only files contained in this directory. The test suite under `analysis/tests/` verifies the regenerated outputs, so run the analysis script before `pytest`.

## Contents

- `data/answers/`: 28 canonical answer files.
- `data/judgments_repaired.csv`: 8,400 judge records.
- `data/majority_votes.csv`: 2,800 majority-vote groups.
- `data/item_metadata.csv`: 100 processed item metadata rows.
- `human_validation/`: sanitized A/B annotator workbooks, the 13-row adjudication summary, the derived 13-row referral-records view pairing each annotator's label with their written reason, corrected post-patch sample manifest, sampling audit, reviewer guide and derived results.
- `analysis/`: scripts, tests, templates, inputs, tables, pinned analysis requirements and manifests. The analysis script also regenerates the Supplementary Information source, the derived figure files and the long-form judge-score projection under `analysis/`; those regenerated outputs are not tracked. The Supplementary Information itself is published with the article rather than duplicated here.
- `figures/`: the three manuscript figures, each as PDF and PNG. The manuscript text itself is not part of this release; see the published article.
- `provenance/`: file hashes, the repaired-layer manifest and the item-level rerun-impact table.

## Data layers and known limitations

The immutable source data are preserved as a separate layer from the provenance-tracked repaired layer used in all reported analyses. Retraction-data and OpenAlex citation counts were retrieved on 2025-12-31. Historical model query times, upstream endpoint mappings and immutable backend snapshots are not recoverable for some runs and are documented as unavailable in `analysis/experiment_metadata_recovered_v3.csv`. The expert annotation used for the human-validation substudy recruited no patients and collected no personal or patient-level data.
