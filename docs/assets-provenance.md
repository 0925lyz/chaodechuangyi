# Bundled Asset Provenance

The production media inventories were replaced from the operator-supplied local folders on
2026-09-15. No media was downloaded or generated during the replacement.

- `assets/brand/jaguartv-logo.png`: supplied JaguarTV Figure 1 logo.
- `assets/channels/`: official broadcast-channel icons from the existing `image2数据库` inventory.
- `assets/video/operation/`: every MP4 from the supplied `中间操作类素材` folder.
- `assets/video/cta/motion/`: every MP4 from the supplied `最后CTA素材` folder.
- `assets/audio/music/`: every MP3/M4A audio file from the supplied `音频/背景音乐` folder.
- `assets/audio/voiceover/`: every WAV from the supplied `音频/CTA口播` folder.

Runtime discovery ignores README, JSON transcript, manifest, and static-image files. Production
does not call TTS or another generation service for music or CTA voice.

Player photographs, club crests, and current-season kits are intentionally not bulk-vendored into
Git. They remain in the licensed `image2数据库`, and each production run must copy only validated
assets into its ignored run directory while retaining source and license evidence.

## Poster Background Assets

`assets/poster/catalog.json` is the only production allowlist for static `fan_crowd` backgrounds.
Each entry records the original source, license/authorization, attribution and SHA-256. The factory
checks all four before copying a file into a production run.

- `assets/poster/fan-crowd/jaguartv-stadium-crowd-20260821.png`: an operator-authorized JaguarTV
  Image2 output copied from the pre-existing controlled `image2数据库` inventory. It is a generic
  stadium-and-stands base with no third-party player identity or team crest. The catalog retains
  its exact source path and hash.

External searches are **not** an authorization. `assets-discover` records daily candidates under
the ignored `runs/<date>_batchN/asset-research/` folder, using agent-reach/Exa and Firecrawl when
configured. A person must verify the license and add an approved, hash-checked catalog record
before any downloaded image can be used in a poster.

`star_faceoff` deliberately has no public bulk library. Its two player portraits must be supplied
for that selected fixture with the current club verification, original URL, license record, local
file path and SHA-256 required by `schemas/research-record.schema.json`.
