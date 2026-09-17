# Retraction-cause and republication-field audit

## Scope

This audit separates the mutually exclusive `primary_retraction_cause` variable from the independent `republication_status` variable. It does not alter benchmark answers, judge records, majority labels, or the locked n=140 human-validation sample.

## Corrected boundary records

| Item | Article | Primary retraction cause | Republication status | Evidence |
|---:|---|---|---|---|
| 28 | *Effects of decontamination of the oropharynx and intestinal tract on antibiotic resistance in ICUs* | `other_or_unclassified` (analysis/coding error) | `Yes` | The supplied retraction notice says one ICU's intervention periods were misclassified and the original article was retracted and replaced. DOI: https://doi.org/10.1001/jama.2014.7247 |
| 32 | *Nuts as a replacement for carbohydrates in the diabetic diet* | `other_or_unclassified` (statistical-analysis error) | `No` for formal corrected republication; `post_retraction_reanalysis=Yes` | The publisher's retraction statement attributes retraction to an unintended statistical error. A later expanded reanalysis of the same trial data was published in another journal (DOI `10.1007/s00125-018-4628-9`), but PubMed/Crossref do not index it as a formal corrected-and-republished replacement. Retraction DOI: https://doi.org/10.2337/dc16-rt02; archived notice: https://pmc.ncbi.nlm.nih.gov/articles/PMC5223408/; reanalysis: https://pmc.ncbi.nlm.nih.gov/articles/PMC6061153/ |
| 73 | *Primary prevention of cardiovascular disease with a Mediterranean diet* (PREDIMED) | `randomisation_irregularities` | `Yes` | The NEJM notice states that the original report was withdrawn because of irregularities in randomisation procedures and replaced by a new report. Retraction notice: https://doi.org/10.1056/NEJMc1806491; replacement report: https://doi.org/10.1056/NEJMoa1800389 |

## Resulting category totals

- `fabrication_or_manipulation`: 46
- `misconduct_or_ethics`: 22
- `other_or_unclassified`: 23
- `duplication_or_overlap`: 7
- `randomisation_irregularities`: 2
- Total: 100

Republication remains a separate field: 2 `Yes`, 86 `No`, and 12 `Unknown` in the supplied metadata.
