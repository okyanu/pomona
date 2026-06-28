# Private folder (local only — gitignored)

Personal and detailed planning files. **Never pushed to GitHub.**

```text
private/
├── README.example.md
├── DAILY_LOG.md, DAILY_PLAN_30_DAYS.md, …
├── research/              ← PDFs, deep research
└── planning/              ← detailed architecture & roadmap
    ├── architecture.full.md
    ├── ROADMAP.full.md
    └── PHASES.full.md
```

**Public (short) docs for everyone:** `docs/architecture.md`, `docs/ROADMAP.md`, `docs/PHASES.md`

## Gitignored

| Pattern | What |
|---------|------|
| `private/**` | All personal & detailed planning |
| `*.pdf` | Reference documents |
| `assets/**` | Screenshots, local files |
| `research/` | Use `private/research/` instead |
