# Screenshot Samples

Each subdirectory is one replayable screenshot sample.

Required files:

- `sample.png`: the screenshot. Prefer redacted real WeChat screenshots for real-world tuning.
- `layout.json`: calibrated or estimated regions in image coordinates.
- `manifest.json`: sample metadata, structured OCR boxes, and expected parser results.

`tools/verify_screenshot_samples.py` defaults to `--provider structured`, which uses `structured_boxes` from the manifest and does not initialize a live OCR model. To test a real OCR engine against the same samples:

```powershell
.venv312\Scripts\python tools\verify_screenshot_samples.py --provider PaddleOCR
```

Before committing real screenshots, redact names, avatars, phone numbers, emails, links, order numbers, and any sensitive chat text. Keep enough layout structure for OCR and page parsing to remain meaningful.

Export a replay result into this format:

```powershell
.venv312\Scripts\python tools\replay_ocr_sample.py path\to\redacted.png --layout path\to\layout.json --provider PaddleOCR --output tmp\replay.json
.venv312\Scripts\python tools\export_screenshot_sample.py --replay-json tmp\replay.json --name wechat_dm_real_redacted_001
```

Export from a WhoChat debug sample:

```powershell
.venv312\Scripts\python tools\export_screenshot_sample.py --debug-sample-dir .whochat-data\debug_samples\sample-xxx --name wechat_dm_debug_redacted_001
```
