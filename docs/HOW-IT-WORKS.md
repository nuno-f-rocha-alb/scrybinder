# How Scrybinder works

Scrybinder identifies the **printing** of a card — not just its name — from a photo. This page explains the pipeline, the design choices and how accuracy is measured.

```
photo / frame
   │  OpenCV: find the card, correct perspective → 630×880 image          (scan/vision.py)
   ├─ OCR  ─ title, set code, collector number, spark / stamp               (scan/identify.py)
   ├─ Vision ─ DINOv2 embeddings of the card and its artwork                (scan/embed.py)
   │            └─ nearest neighbours in a local index of Scryfall images   (scan/index.py)
   ▼
 candidate printings  ── rank: artwork → illustrations, then card + OCR + tie-breakers  (scan/visual.py)
   ▼
 scan list (editable)  ──► collection (SQLite)
```

## 1. Finding the card

`find_card` thresholds the frame with several methods and keeps the largest contour that looks like a card: roughly 63:88 proportions, corners near 90°, a tight fit to its bounding quadrilateral, and fully inside the frame (shapes that touch the frame edge are shadows or background). A second pass accepts incomplete contours — foil glare can break a mask — only if nothing passed the strict test. A perspective warp produces a normalised 630×880 image. A *stability* detector fires the capture when the quadrilateral stays still for 0.4 s and re-arms when the card leaves.

## 2. OCR

Tesseract reads the name from several zones and pre-processings (modern, borderless/showcase, glare-damaged), the bottom strip for the collector number and set code, and a small detector looks for the **spark** symbol that marks The List cards. The name is fuzzy-matched (RapidFuzz) against every non-digital card name in the database. OCR alone resolves most modern cards, but cannot read old decorative fonts, foreign text or foils.

## 3. Visual matching

A local index holds two 768-d vectors per card face from **DINOv2 ViT-B/14**: one for the whole card (frame, layout) and one for the artwork crop. The crop box is calibrated per frame era (1993, 1997, 2003, 2015+, borderless) by aligning Scryfall's own `art_crop` images with the card images. A capture is embedded in the same way — with all candidate crop boxes — and compared by cosine similarity (a matrix product; no approximate-nearest-neighbour library is needed at ~110k rows).

The index lives in `data/index/<model>-<preprocessing hash>/` as 2048-row `.npy` shards plus a small SQLite table of rows. It is resumable, a finished shard is never rebuilt, and changing the model or the pre-processing changes the folder name so incompatible vectors never mix.

## 4. Ranking

The artwork is the strongest signal. It first picks a short list of *illustrations*; within them, printings are ordered by

`score = w_art · cos(art) + w_card · cos(card) + w_name · name match + w_pts · OCR points + priors`

* **OCR points** reward matching set code and collector number. Promo prints (`psos`, `20p`) print their parent set code and a number without the suffix, so they are scored like the regular printing.
* **Tie-breakers**: a promo/prerelease stamp crop is compared among nearly tied candidates; printings you already own gain a little; memorabilia/oversized replicas and serialized variants (`x/500`, identical artwork) lose a little.
* **Rescue**: if the artwork is unusable (strong foil glare) but the OCR name is certain, OCR candidates are boosted.
* Split/aftermath/flip cards have no real art box, so their art vectors are excluded from art matching.
* **Confidence** is `high` when the margin to the second candidate and the artwork similarity are both large, otherwise `medium`/`low`; the UI flags anything that is not high.

Weights live in `scrybinder/scan/visual.py` and can be overridden with `data/scan_weights.json`.

## 5. The scan list

Each read becomes an entry. A new capture of the same printing and finish adds to the quantity for photos and folders (a live camera ignores a card it reads again right after itself, since it is still on the stand); pressing `N` starts a new (foil) entry. Entries can be edited, re-pointed to another printing and removed; **Add to collection** writes them (and a row per entry to `scan_log`, with the top-5 candidates and their signals, for later evaluation).

## Evaluation

`scrybinder-eval` measures accuracy at the printing and illustration level:

* `--set dev` — captures logged in `scan_log` (ground truth is what you confirmed) and photos in `data/test-photos`.
* `--set tune` / `--set synth` — synthetic photos made from Scryfall's `large` images (perspective, blur, noise, glare), stratified by frame era, with different random seeds for tuning and measuring.
* `--set final` — writes an HTML sheet of your own photos with the predictions; you click the wrong ones and pick the correct printing, and `--import-corrections` stores that as ground truth.
* `--grid` searches weights over the recorded signals; `--visual-only` skips OCR for fast iteration.

Results with the complete index (≈112,700 faces):

| Set | Printing top-1 | Illustration top-1 | Printing top-5 |
|---|---|---|---|
| Synthetic, 300 photos (eras 1993–2026, borderless) | 86 % | 97 % | 96 % |
| 6 development photos | 6 / 6 | 6 / 6 | 6 / 6 |
| 44 mixed real photos (after tuning on them — optimistic) | ≈ 95 % | | |

Synthetic photos are rendered from the same Scryfall images that the index uses, so they favour the matcher; the real-photo number was tuned on its own errors. Treat both as upper bounds. The dominant failure is the same artwork printed more than once (The List vs original, prerelease vs promo pack, serialized vs regular), which is why uncertain reads are flagged rather than silently accepted.
