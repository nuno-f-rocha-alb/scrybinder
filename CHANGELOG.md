# Changelog

All notable changes are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
- The updater could not replace `base_library.zip` while the app was running ("the process cannot access the file") and gave up; files Windows keeps locked are now put in place right after you press *Restart now*.

## [0.4.1] — 2026-10-13

### Fixed
- The updater undoes an update that was cut short (crash, power loss, closing the app) the next time Scrybinder starts, instead of leaving a half-replaced app.

## [0.4.0] — 2026-10-13

### Added
- In-app updater: *Settings → Updates* checks the releases on GitHub, downloads only the files that changed (up to three releases behind), verifies their SHA-256 and swaps them in while the app runs, undoing everything if a step fails; then *Restart now*. Optional *Check on start-up* (off by default) puts a dot next to Settings (#19).

### Fixed
- Update packages now include the new `manifest.json`, so the app folder's manifest matches the installed version after an update.

## [0.3.0] — 2026-10-13

### Added
- Optional GPU acceleration for the installed Windows app: *Settings → GPU acceleration* downloads the CUDA build of PyTorch (pinned and checksum-verified), tests it on your GPU, and uses it after a restart; Remove, `SCRYBINDER_NO_GPU=1` and any failure leave the app on the CPU (#9).
- Settings shows which device the visual model runs on.
- Import a Moxfield collection CSV (Import page, `POST /api/import/moxfield`); cards are matched by edition and collector number (#10).

### Changed
- Building the visual index reports progress while it computes vectors (it looked stuck after the first block) and Stop answers between batches (#12).
- README rewritten: install and update steps, binder pages, the visual index with measured timings, GPU acceleration, troubleshooting, and a security and privacy section.

### Fixed
- The Moxfield export wrote language codes (`en`); it now writes the names Moxfield uses (`English`), so it imports back.

## [0.2.0] — 2026-10-13

### Added
- Hover a card image in the scan list (captured photo, chosen printing, printing candidates) to see it enlarged.
- Update packages: each release also publishes `manifest.json` and `Scrybinder-X-update-from-Y.zip` with only the files that changed, instead of a ~1 GB download.
- Scan a whole binder page (up to 3×3 cards) from one photo: *Binder page (3×3)* option on the Scan page, `POST /api/scan/page`, one review-list entry per card (#1).

## [0.1.0] — 2026-10-12

First public release.

### Added
- Collection manager: search, filters, grid/table views with adjustable card size, side-panel editor, bulk edit/delete, per-set progress, group-by-illustration counts.
- Import/export: ManaBox (lossless), Moxfield, Cardmarket; automatic daily refresh of Scryfall bulk data and EUR prices.
- Scanning from photos, a watched folder or a live camera; editable scan list with merging of identical cards, foil entries, prices and running total.
- Visual identification with DINOv2 over a local index of Scryfall images (`scrybinder-index`), OCR tie-breakers, The List spark detection, promo-stamp tie-breaker, support for non-English and foil cards.
- `scrybinder-eval` for measuring accuracy on synthetic photos, logged scans and your own photos.
- Windows installer and portable build (Linux and macOS: run from source).
