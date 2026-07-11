# Wiki staging content

GitHub Wikis live in a **separate git repository** (`pomona.wiki.git`) that
only exists after the first page is created. This folder is *not* that
repository — it is staged Markdown, ready to publish, kept in the main repo
so it is reviewed and versioned like any other change.

## One-time setup (do this once, in the GitHub UI)

1. Go to the repo → **Wiki** tab → **Create the first page**.
2. Give it any title/content (e.g. paste in `Home.md` below) and save. This
   creates the `pomona.wiki.git` repository on GitHub.

## Publish these pages

Once the wiki repo exists, from a machine with GitHub push access:

```bash
git clone https://github.com/Okyanus/pomona.wiki.git
cp wiki/Home.md            pomona.wiki/Home.md
cp wiki/Getting-Started.md pomona.wiki/Getting-Started.md
cp wiki/Architecture.md    pomona.wiki/Architecture.md
cp wiki/Model-Status.md    pomona.wiki/Model-Status.md
cp wiki/Roadmap.md         pomona.wiki/Roadmap.md
cp wiki/FAQ.md             pomona.wiki/FAQ.md
cd pomona.wiki
git add . && git commit -m "docs: populate wiki from staged pages" && git push
```

## Keeping it in sync

Treat `docs/` in the main repo as the **source of truth**; these wiki pages
are short, reader-friendly summaries that link back to `docs/` for full
detail. Update both when a phase completes (see `AGENTS.md` workflow).
