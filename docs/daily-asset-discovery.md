# Daily Poster Asset Discovery

This is the daily intake step between manual fixture selection and the research/production gate.
It finds new sources. It does not download, approve or publish a photo.

## Run It

After `recommend` and `select`, run:

```bash
scripts/discover-poster-assets.sh runs/YYYYMMDD_batch1 YYYY-MM-DD
```

The result is `runs/YYYYMMDD_batch1/asset-research/asset-candidates-YYYYMMDD.json`.

The command sends every query to both sources:

1. agent-reach's Exa integration discovers public Commons pages and keeps its raw discovery output.
2. Firecrawl searches and scrapes the matching pages when `FIRECRAWL_API_KEY` is configured.

If Firecrawl is not configured, the manifest records `not_configured`; it does not pretend Exa is
a Firecrawl result. The command still retains Exa candidates so the operator can inspect them.

## Approval Before Use

For each candidate, verify the original page, author, license, permitted commercial/derivative use,
and whether the image is actually current and relevant to the selected match. Then download the
approved file into `assets/poster/`, calculate SHA-256, and add one `status: approved` record to
`assets/poster/catalog.json`. Never add a raw search result directly to the catalog.

For player portraits, do not use the shared fan catalog. Add both portraits to the selected
fixture's research JSON and include `current_club_verified: true`, `license_record`, `local_path`,
and `asset_hash`. A missing, stale, unlicensed or altered player image blocks `star_faceoff`.

## Dry-Run Check

```bash
scripts/discover-poster-assets.sh runs/demo_batch1 2026-09-06 --dry-run
```

This creates the manifest shape without calling Exa, Firecrawl or downloading media.
