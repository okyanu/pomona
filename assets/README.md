# Local assets (not in Git)

This folder is **gitignored**. Keep private or large files here:

- Dataset archives (`.7z`, `.zip`, large `.csv`)
- Screenshots and personal notes
- PDFs and reference documents
- Anything you do not want on GitHub

## Public model weights

Do **not** store model checkpoints here. Use Hugging Face:

- [Okyanus/ai-pomona-agronomist-gemma4](https://huggingface.co/Okyanus/ai-pomona-agronomist-gemma4)

Local training checkpoints belong in `models/checkpoints/` (also gitignored).

## Optional layout

```text
assets/
├── datasets/       # AGC2 and other raw data
├── screenshots/    # dev screenshots
└── notes/          # private working notes
```

Copy this structure locally; it will not be pushed to GitHub.
