# Data, storage and formats

## Where things are stored

| Location | When |
|---|---|
| `./data` | running from a source checkout |
| `%LOCALAPPDATA%\Scrybinder` | installed Windows build |
| `~/Library/Application Support/Scrybinder` | installed macOS build |
| `~/.local/share/scrybinder` (or `$XDG_DATA_HOME/scrybinder`) | installed Linux build |
| `<app folder>/data` | portable zip: a `data` folder or a `portable.txt` next to the executable |
| `$SCRYBINDER_DATA` | overrides everything above |

Inside that folder:

| Path | Content |
|---|---|
| `scrybinder.db` | SQLite (WAL): cards, collection, set totals, scan log |
| `bulk/` | the downloaded Scryfall bulk file |
| `images/{small,normal,large}/` | cached card images (the visual index uses `normal`, ~100 KB each) |
| `index/` | the visual index (vectors, `rows.db`, manifest) |
| `captures/` | scan captures and `reads.json` (the unsaved scan list) |
| `trash/` | JSON copies of rows removed by bulk delete |
| `scrybinder.log` | log of packaged builds that run without a console |

**Back up** by copying the folder while the app is closed (the database uses WAL, so copy `-wal`/`-shm` too, or use `sqlite3 scrybinder.db ".backup copy.db"`). `images/` and `index/` can be rebuilt; `scrybinder.db` and `captures/` cannot.

## Collection model

Rows are aggregated by (printing, finish, condition, language, location, altered, signed, misprint, proxy) with a quantity: the same card in two boxes is two rows, and *Move* merges rows automatically. The printing is always the Scryfall id of the exact printing. Prices are the EUR (Cardmarket) values from Scryfall's bulk data for the row's finish.

## Network use

| Host | What for |
|---|---|
| `api.scryfall.com` | bulk-data metadata (one call per update), set list |
| `*.scryfall.io` (cards, svgs) | card images and set icons, ≥ 100 ms apart |
| `huggingface.co` | the DINOv2 weights, once, when the visual index is first used |

Scrybinder sends `User-Agent: Scrybinder/<version>` as Scryfall's guidelines require. It updates the bulk data at most once a day.

## Import / export

* **ManaBox** CSV — round trip is lossless (ManaBox id, condition, flags, price, date).
* **Moxfield** collection CSV — the location goes into `Tags`.
* **Cardmarket** stock list — by `cardmarketId`; condition and language mappings are approximate (NM→NM, LP→EX, MP→GD, HP→PL, DMG→PO). Cards without a `cardmarketId` or with a language Cardmarket has no code for are skipped. Check a small file before uploading stock.
