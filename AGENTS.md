# 朝的创意 Static Prematch Poster Factory

These rules apply to every task and automation in this repository.

## Routing and assets

- Use the large model selected for the current task by default. Do not hard-code obsolete text-model names.
- Use the configured active `gpt-image-2` route first and the configured APIMart route only as an explicit recorded fallback.
- The upper-right JaguarTV logo must be the exact Figure 1 asset and must be baked into each final poster exactly once.
- Image2 creates only the clean 4:5 visual background. The compositor adds the logo, team data, channel icons, official crests, and pt-BR copy deterministically to a 2048x2560 PNG.
- Every match poster must resolve and validate both official club crests before production. Missing or corrupt crests stop the run.
- A `star_faceoff` background requires current, licensed research evidence for one player from each team. Without both records, it stops when forced and falls back to `fan_crowd` only when style is `auto`.
- Player, crest, kit, and channel assets used by this project must be authorized and recorded in the run evidence.

## Static-only workflow

- This repository produces static PNG posters only. Do not generate video, hooks, audio, TTS, CTA media, or a video upload from this workflow.
- Daily automation runs `scripts/task1_launcher.sh <1|2|3>` in its default `recommend` stage. It creates recommendations and stops.
- An operator must review `phase1/recommended-fixtures.json` and run `jaguartv-prematch select` before production. The system must never turn recommendations into posters automatically.
- After selection, run `scripts/task1_launcher.sh <batch> --stage produce --date YYYYMMDD`. It validates research, generates backgrounds, composites posters, runs PNG QA, and delivers image files locally.
- Keep `provider_id` and `model_id` as separate fields in records and manifests. Never place credentials, tokens, cookies, or account-session files in the repository.

## Publish copy and safety

- Visible copy is concise, natural pt-BR and contains an editorial prediction only when supported by current research.
- Do not claim offers, free trials, service quality, or availability that the run has not verified.
- Stop at the first unavailable required integration and report a sanitized error.
