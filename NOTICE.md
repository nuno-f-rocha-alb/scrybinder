# Notices and credits

Scrybinder's own source code is released under the [MIT License](LICENSE). It builds on the software and data below, each under its own terms.

## Magic: The Gathering and Scryfall

- *Magic: The Gathering* — card names, artwork, frames and symbols — is property of **Wizards of the Coast LLC**. Scrybinder is an unofficial fan project, free of charge, not produced, endorsed, supported or affiliated with Wizards of the Coast. It follows the spirit of the [Wizards of the Coast Fan Content Policy](https://company.wizards.com/en/legal/fancontentpolicy).
- Card data, prices (EUR/Cardmarket), set icons and card images come from **[Scryfall](https://scryfall.com)** through its public API and CDN, used according to the [Scryfall API guidelines](https://scryfall.com/docs/api) (identifying `User-Agent`, rate-limited requests, bulk data instead of per-card calls, no re-selling of data). Scrybinder is not affiliated with Scryfall.
- The test suite includes a handful of Scryfall card images (`tests/fixtures/cards`) used only to check recognition code.

## Software

| Component | Licence |
|---|---|
| Python, FastAPI, Starlette, Uvicorn, HTTPX, ijson | PSF / MIT / BSD-3 |
| pywebview | BSD-3 |
| OpenCV (opencv-python-headless) | Apache-2.0 (OpenCV), MIT (wheel) |
| NumPy | BSD-3 |
| RapidFuzz | MIT |
| pytesseract, **Tesseract OCR** (bundled in Windows builds) | Apache-2.0 |
| PyTorch, torchvision | BSD-3 |
| Hugging Face Transformers | Apache-2.0 |
| **DINOv2** model weights (`facebook/dinov2-base`) by Meta AI | Apache-2.0 |
| React, Vite, Tailwind CSS, Tabler Icons | MIT |
| PyInstaller (packaging only) | GPL-2.0 with bootloader exception |
| Inno Setup (Windows installer, build time only) | Inno Setup licence |

The DINOv2 weights are downloaded from the Hugging Face Hub the first time the visual index is used (or bundled in release builds). Tesseract's English language data (`eng.traineddata`) is Apache-2.0.

If you spot a missing or incorrect attribution, please open an issue.
