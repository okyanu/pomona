# License and Attribution

Pomona platform code is Apache-2.0. Dataset source material may have different licenses and must be checked before reuse, transformation, or redistribution.

## Rules for Dataset Work

- Keep raw third-party datasets outside Git history.
- Record each source in `datasets/sources/*.yaml` before using it.
- Register only sources with clear license terms that allow derived Pomona labels on Hugging Face.
- Prefer sources with clear academic or open-data terms (CC BY 4.0 for current v0.1 externals).
- Preserve attribution in `datasets/pomona-tomato-risk-v0.1/LICENSES.md`.
- Publish only clean derived artifacts to Hugging Face.

## Active v0.1 Sources

| Source | License | Redistribution | Derived labels | Attribution |
|---|---|---|---|---|
| `udea_greenhouse_tomato` | CC BY 4.0 | Allowed | Allowed | Required |
| `4tu_autonomous_greenhouse_challenge` | CC BY 4.0 | Allowed | Allowed | Required |
| `pomona_handwritten_eval_cases` | Apache-2.0 (Pomona) | Allowed | Allowed | Pomona project |

## Verified External Sources

### udea_greenhouse_tomato

- Title: Mobile and Manual Dataset for Greenhouse Tomato Crop
- DOI: `10.5281/zenodo.16745909`
- URL: `https://zenodo.org/doi/10.5281/zenodo.16745909`
- License: CC BY 4.0
- Verification date: 2026-06-30
- Attribution required: yes
- Raw data policy: keep local only in `datasets/raw/`; never commit raw files.
- Downloaded raw file: `datasets/raw/udea_greenhouse_tomato/DB_Mobile_Manual_Tomato.csv` (ignored by Git)

### 4tu_autonomous_greenhouse_challenge

- Title: 4th Autonomous Greenhouse Challenge: Dwarf Tomato Timeseries and Images
- DOI: `10.4121/fa102772-32db-4b30-bace-12f2016722ce.v1`
- URL: `https://data.4tu.nl/datasets/fa102772-32db-4b30-bace-12f2016722ce/1`
- License: CC BY 4.0
- Verification date: 2026-06-30
- Attribution required: yes
- Raw data policy: keep local only in `datasets/raw/`; never commit raw files.
- Downloaded raw files: `datasets/raw/4tu_autonomous_greenhouse_challenge/README.md` and `datasets/raw/4tu_autonomous_greenhouse_challenge/autonomous_greenhouse_challenge4_timeseries.zip` (ignored by Git)
- Skipped raw file: canopy camera zip, because it is about 31 GB and not needed for the compact v0.1 reasoner dataset.

## Excluded From v0.1

### mendeley_hydroponics_fertigation

- License: CC BY 4.0, but excluded from v0.1 because the available file is a DOCX with embedded tables rather than a clean CSV/JSON/XLSX dataset.
- Future use requires table extraction and quality review.

## Attribution Checklist

For every source, capture:

- Source title and stable URL.
- DOI, if available.
- License text or license URL.
- Allowed use notes.
- Redistribution limits.
- Required citation or attribution.
- Verification status.

## Safety Scope

Dataset labels must not encourage direct pesticide dosage, unsafe chemical recommendations, autonomous fertigation changes, direct actuator control, or definitive disease diagnosis without evidence. Those behaviors belong in blocked actions and human review flows.
