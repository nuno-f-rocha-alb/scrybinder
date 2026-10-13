# Scrybinder

**Scan, identify and catalogue your Magic: The Gathering collection — locally, for free.**

Scrybinder is a desktop app that recognises the *exact printing* of each card you show to a camera (or drop in as a photo), lets you review the results in an editable list, and keeps your collection in a local database. It imports and exports ManaBox, Moxfield and Cardmarket CSVs, uses Scryfall for card data and shows Cardmarket prices in EUR. No account, no subscription, no cloud: your collection never leaves your computer.

[![CI](https://github.com/nuno-f-rocha-alb/scrybinder/actions/workflows/ci.yml/badge.svg)](https://github.com/nuno-f-rocha-alb/scrybinder/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Release](https://img.shields.io/github/v/release/nuno-f-rocha-alb/scrybinder?include_prereleases)](https://github.com/nuno-f-rocha-alb/scrybinder/releases)

![Collection view](docs/images/collection.jpg)

<table>
  <tr>
    <td width="50%"><img src="docs/images/scan-list.jpg" alt="Scan list"><br><sub><b>Scan list</b> — scanned cards wait in an editable list; nothing touches your collection until you press Add.</sub></td>
    <td width="50%"><img src="docs/images/editor.jpg" alt="Card editor"><br><sub><b>Card editor</b> — quantity, finish, condition, language, location, purchase data, notes.</sub></td>
  </tr>
  <tr>
    <td width="50%"><img src="docs/images/add.jpg" alt="Add cards"><br><sub><b>Add by name</b> — pick the exact printing from every printing Scryfall knows.</sub></td>
    <td width="50%"><img src="docs/images/sets.jpg" alt="Sets"><br><sub><b>Sets</b> — how much of each set you own.</sub></td>
  </tr>
</table>

## Features

- **Exact-printing recognition.** Card name and set/number are read with OCR; the artwork and frame are matched against a local index of Scryfall images with a DINOv2 vision model. Promo stamps, The List cards, foils, borderless and showcase frames, and non-English cards are handled — see [How it works](docs/HOW-IT-WORKS.md).
- **Photos, folders or a live camera.** Drop photos, watch a folder that another program saves into, or point a webcam / capture card at your cards. Identical cards in a row add up; press `N` before a foil to start a new entry.
- **Review before you commit.** Every scan lands in a list where you can change the printing, finish, quantity, condition and language. Uncertain reads are flagged. Prices and a running total are shown.
- **A real collection manager.** Search, filter, group by set, edit in bulk, move cards between boxes, track purchase price and date, see per-set completion. Deleted rows are saved to a trash file first.
- **Import / export.** ManaBox (lossless round trip), Moxfield and Cardmarket stock lists.
- **Private by design.** Everything is stored in a local SQLite database. The only network traffic is to Scryfall (card data, prices and images).
- **Works without a GPU.** The vision model runs on CPU; an NVIDIA GPU just makes building the index much faster.

## How it compares

| | Scrybinder | ManaBox / Delver Lens | [LoreFetch](https://github.com/jnapoli87/LoreFetch) |
|---|---|---|---|
| Runs on | Windows (Linux/macOS from source) | Phone | Windows |
| Account / subscription | none | free tiers | none |
| Data stays on your PC | yes | no (cloud sync) | yes |
| Exact printing (promos, foils, serialized) | yes, with a review list | scanning picks a printing | yes |
| Import / export | ManaBox, Moxfield, Cardmarket | own formats | CSV |
| Open source | MIT | no | GPL-3.0 |

Scrybinder does not do deck building, price history or mobile scanning; use it alongside tools like Moxfield, Archidekt or ManaBox.

## Download

Get the latest build from the [Releases page](https://github.com/nuno-f-rocha-alb/scrybinder/releases).

| Platform | File | Status |
|---|---|---|
| Windows 10/11 | `Scrybinder-Setup-x.y.z.exe` (installer) or `Scrybinder-x.y.z-windows-portable.zip` | tested |
| Linux, macOS | run from source (see [docs/BUILDING.md](docs/BUILDING.md)) | works in CI tests; no ready-made build yet |

The binaries are not code-signed, so Windows SmartScreen may warn on first launch (*More info → Run anyway*). Each release lists SHA-256 checksums.

The Windows builds bundle Tesseract; on Linux and macOS install it yourself (`sudo apt install tesseract-ocr`, `brew install tesseract`). If your system has no native web view, Scrybinder opens in your browser instead.

## First steps

1. **Download the card database.** *Settings → Update bulk data now* fetches Scryfall's "Default Cards" file (~80 MB) once. Scrybinder refreshes it automatically at start-up when it is more than a day old, which is how prices stay current.
2. **Import what you have (optional).** *Import / Export → Import from ManaBox* takes the CSV exported from ManaBox; cards are matched by their Scryfall id, so the exact printing is kept.
3. **Scan.** *Scan* → drop photos, watch a folder or start a camera. Check the list, set the location, press **Add to collection**.
4. **Build the visual index (recommended).** Without it Scrybinder identifies cards from OCR only. With it, artwork decides — including cards whose text OCR cannot read. See below.

### Scanning a binder page

Turn on **Binder page (3×3)** in the Scan page and drop a photo of a whole binder page (or let the watched folder pick them up): up to 9 cards are found and each one lands in the review list as its own entry. Shoot the page upright and as large as you can (photos are used up to 4500 px; each card needs about 600 px of height to be read reliably), with the cards in their pockets. The pockets are found from their outline and an empty pocket is told from a card by the light and dark bands of a card (title bar, art, text box), so a glossy empty pocket is not taken for one. It was measured on black binders; pages filled row by row (the last page of a binder) and pages with some empty pockets work, and a page holding a single card is read like a normal photo. Very strong reflections can hide a card, and light binders are less tested. Live camera capture is still one card at a time.

### Scanning tips

- One card per photo on a plain background; light from the side, not from beside the lens.
- Live cameras: a fixed overhead stand and a stable light work best. Virtual cameras that only speak Media Foundation (for example Sony *Imaging Edge Webcam*) show a black picture to OpenCV — use a UVC webcam or an HDMI capture card instead.
- The capture triggers when a card stays still for 0.4 s and re-arms when it leaves the frame.
- `N` marks the next card as foil / a new entry. In the one-by-one confirmation mode (turn *List mode* off): `Enter` accept, `Esc` discard, `←`/`→` change printing, `F` foil, `C` condition, `L` language, `+`/`-` quantity.

### The visual index

Open **Settings → Visual index** and press **Build pilot index** (~5,000 printings, a few minutes) or **Build full index…** (every printing: ~110,000 images, ~12 GB, several hours). Progress is shown there, it can be stopped and resumed, and running it again only adds new printings. The released builds include everything needed (PyTorch CPU).

From source, or for scripting, the same job is available on the command line:

```bash
uv sync --extra vision
uv run scrybinder-index --pilot
uv run scrybinder-index --all
```

NVIDIA GPU: `uv sync --extra vision-cuda`. The index is built from Scryfall's images at the standard rate limit (10 requests per second) and can be stopped and resumed.

## Accuracy and limitations

Measured on our own test photos (see [How it works](docs/HOW-IT-WORKS.md#evaluation)): about 95 % of printings were right on a mixed set of 44 real photos after tuning on them, and 86 % (printing) / 97 % (illustration) / 96 % (top-5) on 300 synthetic photos with the full index. Most errors are the *same card printed identically* — The List vs the original, prerelease vs promo-pack stamps — where the image genuinely does not tell them apart; those are flagged for review.

Known limits: Room/split cards (the artwork box does not exist), very strong holographic foils, serialized cards (identical art — you confirm), cards photographed through glare or sleeves, and non-Latin scripts for OCR (artwork still works). A live camera needs good light. Always glance at the list before adding.

## Build from source

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/), Node.js 20+, Tesseract OCR.

```bash
git clone https://github.com/nuno-f-rocha-alb/scrybinder.git && cd scrybinder
uv sync --extra vision          # or no extra for OCR-only; --extra vision-cuda for an NVIDIA GPU
cd ui && npm ci && npm run build && cd ..
uv run scrybinder               # desktop window; add --browser or --serve for a browser tab
uv run pytest                   # tests
```

Packaging (PyInstaller, Windows installer) is described in [docs/BUILDING.md](docs/BUILDING.md).

## Data and privacy

Your data lives in one folder: `data/` when run from source, `%LOCALAPPDATA%\Scrybinder` (Windows), `~/Library/Application Support/Scrybinder` (macOS) or `~/.local/share/scrybinder` (Linux) for installed builds, or wherever `SCRYBINDER_DATA` points. It holds the SQLite database, cached card images and the vector index. Scrybinder talks only to `api.scryfall.com` and `cards.scryfall.io` (card data, prices, images, set icons); there is no telemetry. The local server listens on `127.0.0.1` only and is protected by a per-session token. Back up by copying the folder with the app closed. See [docs/DATA.md](docs/DATA.md).

## Contributing

Issues and pull requests are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). Bug reports with a photo that was misidentified are especially useful (card, what you expected, what you got).

## Legal

Scrybinder is an unofficial fan project, free of charge, and is not produced, endorsed, supported or affiliated with Wizards of the Coast. *Magic: The Gathering* and its card names, images and symbols are property of Wizards of the Coast LLC. Card data, prices and images are provided by [Scryfall](https://scryfall.com); this project is not affiliated with Scryfall. Cardmarket prices come from Scryfall's data and are indicative. See [NOTICE.md](NOTICE.md) for third-party software and data credits.

Source code: [MIT License](LICENSE).
