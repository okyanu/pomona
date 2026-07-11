# Licenses

Pomona-generated scaffold files in this directory are licensed under Apache-2.0, matching the main Pomona repository.

Third-party raw datasets are not redistributed here. Active v0.1 sources are tracked in `../../sources/` and summarized below.

## Active v0.1 Sources

### udea_greenhouse_tomato

- Title: Mobile and Manual Dataset for Greenhouse Tomato Crop
- DOI: `10.5281/zenodo.16745909`
- URL: `https://zenodo.org/doi/10.5281/zenodo.16745909`
- License: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
- Raw data stays at the original Zenodo/UDEA source or local ignored `datasets/raw/`.
- Derived Pomona labels may be published with attribution and change notices.

### 4tu_autonomous_greenhouse_challenge

- Title: 4th Autonomous Greenhouse Challenge: Dwarf Tomato Timeseries and Images
- DOI: `10.4121/fa102772-32db-4b30-bace-12f2016722ce.v1`
- URL: `https://data.4tu.nl/datasets/fa102772-32db-4b30-bace-12f2016722ce/1`
- License: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
- Raw data stays at the original 4TU source or local ignored `datasets/raw/`.
- Derived Pomona labels may be published with attribution and change notices.
- v0.1 uses the timeseries archive only; the canopy camera image archive is skipped.

### pomona_handwritten_eval_cases

- License: Apache-2.0 (Pomona project)
- Hand-written seed and evaluation JSONL authored by the Pomona project.

### pomona_generated_normal_calibration

- License: Apache-2.0 (Pomona project)
- Generated no-risk calibration rows authored by Pomona scripts.
- These records are safe-range variations derived from clean normalized no-risk records. They are included to teach compact models routine-monitoring behavior and reduce false positives.
- They do not redistribute raw third-party files.

## Before Publishing a Generated Release

1. Confirm each registered source still permits derived-label redistribution.
2. Add source-specific citations here when large-scale derived records are included.
3. Exclude raw third-party files from the Hugging Face dataset repo.
