# Changelog

All notable changes are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
- The right-click menu no longer closes by itself when opened near the bottom of a short window: it is placed inside the window (scrolling inside itself when taller than it), takes focus without scrolling the page, and scrolling the menu does not close it.

## [0.6.1] — 2026-10-15

### Added
- Decks: every group of cards can be folded with a click on its title ("Fold all" / "Unfold all" next to the view options; the choice is remembered), and the bar to add cards stays at the top while you scroll the deck.
- Card details: "View details" (in the card menus of the decks, the collection, the Add page and a deck's card search) opens the card with its image, prices, rules text, printing, all its printings, legality in every format and its rulings (fetched from Scryfall the first time, then kept), with Prev / Next and the arrow keys.
- Decks: several lines of the same card, each with its own printing (for example basic lands in different arts). "Separate line" in the add bar and "Add one as a new line" in the card menu create a line of its own instead of adding to the existing one.
- Decks: a card now has a finish. Switch printing has a button per finish each printing comes in (Select, Select foil, Select etched), says how many of each finish you own, shows the card large when you point at it, and the deck shows the edition (set and number) and the finish of each card. Deck lists exported and imported keep both: `(SET) number` and `*F*` / `*E*` for foil and etched.

### Fixed
- In the list view of a deck the lands (which have no mana cost) lined up one column to the left of the other cards.
- Reversible cards (the same card on both faces, for example Blood Crypt ECL #349) are printings of their card again: they were missing from the printing lists. Existing collections are fixed at the next start.
- Decks: "Add this printing to collection…" (in the copies dialog and the card menu) adds copies of the printing and finish a card asks for, also when you own the card in another printing.
- Switch printing no longer shows a "Foil" badge on printings that merely exist in foil.

## [0.6.0] — 2026-10-15

### Added
- Collection: "New location" makes an empty location to move cards into later (it stays in the list while empty, and can be removed while it has no cards).
- A right-click menu also in the collection (grid and table), on the printings of the Add page and on the results of a deck's card search: edit, add a copy, add to a deck or board, select, copy the name, Scryfall and Cardmarket.
- Decks: a right-click menu on every card in every view (switch printing, add or remove one, move to another board, set as commander, add to another deck or to the collection, tags, details, copy the name, set the deck image, Scryfall and Cardmarket), with Alt+1 to Alt+4 shortcuts on the card under the pointer.
- Collection: a mark on the cards that are in a deck, the decks listed in the edit panel, and "Release and continue" when an edit, move or delete would take copies away from decks (also for bulk edit and delete).
- Decks: add the missing copies of a deck to your collection (all of them, or chosen cards), in a location you pick; they are assigned to the deck.
- Decks: choose the printing of a card from a list of all its printings (image, set, price, finishes, how many you own), with "Use cheapest" and a hint when you own another printing.
- A Code of Conduct (Contributor Covenant 2.1) and an accessibility statement with the known limitations and how to report a barrier, linked from the README.

### Fixed
- The mana curve chart grows to fill its card instead of leaving empty space under it.
- The summary bar of a deck is always pinned to the bottom of the window, whatever the number of cards.

## [0.5.1] — 2026-10-15

### Added
- Log files in the data folder: `app.log` (what the app does and every exception, including those of background threads and the web server) and `crash.log` (the Python stack of every thread when the process dies from a native crash). The camera logs when it opens, its first frame and why it stops.
- *Save a debug frame* on Scan → Camera, and every capture of the camera, save the whole frame with the outline the app found in `debug/` (the last 30 are kept), for reports about cards that are not detected.

### Fixed
- The live camera picture is no longer a continuous stream: in the installed app it went black while cards were still being read, and the page crashed when the camera was stopped.
- A card standing in a card dock is no longer captured again and again when the detector flips between the whole card and a part of it, and a card swapped in the same place is now read (the capture compares what is inside the outline).
- In the scan list, only identical cards in a row add up; a card read again after others is a new line instead of changing an entry far up the list. Identical lines still meet when the list goes into the collection. The line that just changed is outlined for a moment.

## [0.5.0] — 2026-10-13

### Added
- **Decks** (#33). A new *Decks* page to build decks from your collection and from cards you do not own, in folders.
  - Commander, Standard, Pioneer, Modern, Legacy, Vintage and Pauper have deck rules (banned cards, copy limits and their exceptions, deck size, singleton, commander eligibility and pairs, colour identity, game changers); the legality panel lists what is wrong.
  - Reserve **copies of your collection** for a card and see what is assigned, free, in other decks or missing, with the cost to complete. Tag a card **proxy** and it never counts as missing and never enters your collection. Changing a collection row that is assigned to a deck is refused, naming the decks.
  - Five views (List, Compact, Grid, Stacks, Spoiler), grouping by type, colour, mana value, tag or collection status, sorting, and a big card preview that follows the pointer.
  - Statistics: mana curve, colour symbols against land sources, types, tags, average mana value, price, and the chance of having enough lands by a given turn; the charts filter the list.
  - A search for cards to add (name, rules text, type, colours, mana value, only owned, only legal), and import and export of Moxfield / Archidekt / MTGO text lists.
  - The card rules come from the Scryfall file you already download; existing installs fill them in from the cached file at the next start (no new download).

### Fixed
- A console window no longer flashes the first time a photo is read (the Tesseract version check opened one).
- Rare "API misuse" errors when the page asked for several things at once (the shared database connection no longer caches statements).

## [0.4.4] — 2026-10-13

### Fixed
- Restarting after an update no longer flashes console windows (the helper script was started without a console, so each `ping`/`move` opened its own).

## [0.4.3] — 2026-10-13

### Fixed
- Exporting a CSV opens a native *Save as* dialog instead of the generic Edge downloads popup (#26).
- A second Scrybinder window opened while an update is being applied no longer undoes it (the swap holds a lock; a crashed update is still undone at the next start).

## [0.4.2] — 2026-10-13

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
