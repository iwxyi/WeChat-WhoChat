from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.export_screenshot_sample import export_sample_from_replay
from tools.verify_screenshot_samples import _verify_manifest


DATA_DIR = ROOT / "tmp" / "screenshot_sample_export_verify"


def main() -> int:
    shutil.rmtree(DATA_DIR, ignore_errors=True)
    DATA_DIR.mkdir(parents=True)
    source_sample = ROOT / "fixtures" / "screenshot_samples" / "wechat_dm_synthetic"
    replay = _replay_from_manifest(source_sample)
    replay_path = DATA_DIR / "replay.json"
    replay_path.write_text(json.dumps(replay, ensure_ascii=False, indent=2), encoding="utf-8")

    output_root = DATA_DIR / "samples"
    sample_dir = export_sample_from_replay(replay_path, name="exported synthetic sample", output_root=output_root)
    manifest = sample_dir / "manifest.json"
    if not manifest.exists() or not (sample_dir / "sample.png").exists() or not (sample_dir / "layout.json").exists():
        raise RuntimeError(f"exported sample is incomplete: {sample_dir}")
    _verify_manifest(manifest, "structured", "ch", 0.5, False)
    print(f"exported={sample_dir}")
    return 0


def _replay_from_manifest(sample_dir: Path) -> dict:
    manifest = json.loads((sample_dir / "manifest.json").read_text(encoding="utf-8"))
    layout = json.loads((sample_dir / "layout.json").read_text(encoding="utf-8"))
    return {
        "image": str((sample_dir / manifest["image"]).resolve()),
        "engine": "structured-export-verify",
        "warning": None,
        "layout": layout,
        "page": {
            "type": manifest["expected"]["page_type"],
            "confidence": manifest["expected"]["min_page_confidence"] + 0.02,
            "can_generate_reply": manifest["expected"]["can_generate_reply"],
            "reason": "verify export",
        },
        "boxes": [
            {
                "text": box["text"],
                "rect": box["rect"],
                "confidence": box["confidence"],
                "region": "unknown",
                "source": "verify",
            }
            for box in manifest["structured_boxes"]
        ],
        "messages": [
            {
                "speaker": message["speaker"],
                "text": message["text"],
                "rect": [0, 0, 1, 1],
                "confidence": 0.9,
                "partial": message["partial"],
                "reason": "verify",
                "time_text": message.get("time_text"),
            }
            for message in manifest["expected"]["messages"]
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())
