from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    args = _parse_args()
    output_root = Path(args.output_root).resolve()
    if args.debug_sample_dir:
        output = export_sample_from_debug_sample(
            Path(args.debug_sample_dir).resolve(),
            name=args.name,
            output_root=output_root,
            force=args.force,
        )
    else:
        if not args.replay_json:
            raise SystemExit("either --replay-json or --debug-sample-dir is required")
        replay_path = Path(args.replay_json).resolve()
        if not replay_path.exists():
            raise SystemExit(f"replay JSON does not exist: {replay_path}")
        output = export_sample_from_replay(
            replay_path,
            name=args.name,
            output_root=output_root,
            force=args.force,
        )
    print(f"sample={output}")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert replay/debug output into a screenshot sample fixture.")
    parser.add_argument("--replay-json", help="JSON produced by tools/replay_ocr_sample.py --output")
    parser.add_argument("--debug-sample-dir", help="Directory produced by the app diagnostics '保存调试样本' action")
    parser.add_argument("--name", required=True, help="Sample directory name, e.g. wechat_dm_real_redacted_001")
    parser.add_argument("--output-root", default=str(ROOT / "fixtures" / "screenshot_samples"))
    parser.add_argument("--force", action="store_true", help="Overwrite an existing sample directory")
    return parser.parse_args()


def export_sample_from_replay(replay_path: Path, *, name: str, output_root: Path, force: bool = False) -> Path:
    data = json.loads(replay_path.read_text(encoding="utf-8"))
    image_path = Path(data["image"]).resolve()
    if not image_path.exists():
        raise FileNotFoundError(f"image referenced by replay JSON does not exist: {image_path}")
    sample_name = _safe_sample_name(name)
    target = output_root / sample_name
    if target.exists():
        if not force:
            raise FileExistsError(f"sample already exists: {target}")
        shutil.rmtree(target)
    target.mkdir(parents=True)

    image_target = target / "sample.png"
    shutil.copy2(image_path, image_target)
    layout = _layout_for_fixture(data["layout"])
    (target / "layout.json").write_text(json.dumps(layout, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "name": sample_name,
        "image": "sample.png",
        "layout": "layout.json",
        "source": {
            "target_app": str(data.get("target_app") or data.get("source", {}).get("target_app") or ""),
            "app_label": str(data.get("app_label") or data.get("source", {}).get("app_label") or ""),
        },
        "notes": "Exported from replay_ocr_sample.py. Review and redact screenshots/text before committing real samples.",
        "structured_boxes": [
            {
                "text": str(box["text"]),
                "rect": list(box["rect"]),
                "confidence": float(box["confidence"]),
            }
            for box in data.get("boxes", [])
        ],
        "expected": {
            "page_type": data["page"]["type"],
            "can_generate_reply": bool(data["page"]["can_generate_reply"]),
            "min_page_confidence": max(0.0, round(float(data["page"]["confidence"]) - 0.02, 2)),
            "messages": [
                {
                    "speaker": message["speaker"],
                    "text": message["text"],
                    "partial": bool(message["partial"]),
                    "time_text": message.get("time_text"),
                }
                for message in data.get("messages", [])
            ],
        },
    }
    (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def export_sample_from_debug_sample(sample_dir: Path, *, name: str, output_root: Path, force: bool = False) -> Path:
    diagnostics_path = sample_dir / "diagnostics.json"
    if not diagnostics_path.exists():
        raise FileNotFoundError(f"diagnostics.json not found: {diagnostics_path}")
    data = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    pipeline = data.get("pipeline", {})
    image_path = _debug_sample_image(sample_dir, pipeline)
    if image_path is None:
        raise FileNotFoundError("debug sample does not contain the captured screenshot; enable debug screenshot saving first")
    replay_like = {
        "image": str(image_path.resolve()),
        "source": {
            "target_app": pipeline.get("last_result_target_app") or "",
            "app_label": pipeline.get("last_result_app_label") or "",
        },
        "layout": pipeline["last_result_layout"],
        "page": {
            "type": pipeline["last_result_page"],
            "confidence": pipeline.get("last_result_page_confidence") or 0.0,
            "can_generate_reply": pipeline["last_result_page"] in {"chat_dm", "chat_group", "file_helper"},
        },
        "boxes": [
            {
                "text": box["text"],
                "rect": _rect_from_debug(box["rect"]),
                "confidence": box["confidence"],
            }
            for box in pipeline.get("last_result_ocr_boxes", [])
        ],
        "messages": [
            {
                "speaker": message["speaker"],
                "text": message["text"],
                "partial": message["partial"],
                "time_text": message.get("time_text"),
            }
            for message in pipeline.get("last_result_parsed_messages", [])
        ],
    }
    temp_replay = sample_dir / "_whochat_replay_export.json"
    temp_replay.write_text(json.dumps(replay_like, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        return export_sample_from_replay(temp_replay, name=name, output_root=output_root, force=force)
    finally:
        try:
            temp_replay.unlink()
        except OSError:
            pass


def _debug_sample_image(sample_dir: Path, pipeline: dict[str, Any]) -> Path | None:
    source = pipeline.get("last_result_image")
    if source:
        candidate = sample_dir / Path(str(source)).name
        if candidate.exists():
            return candidate
        source_path = Path(str(source))
        if source_path.exists():
            return source_path
    images = sorted(sample_dir.glob("*.png"))
    return images[0] if images else None


def _rect_from_debug(value: Any) -> list[int]:
    if isinstance(value, dict):
        return [int(value["left"]), int(value["top"]), int(value["right"]), int(value["bottom"])]
    return [int(item) for item in value]


def _layout_for_fixture(layout: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for key in [
        "window_rect",
        "nav_rect",
        "chat_list_rect",
        "content_rect",
        "title_rect",
        "message_rect",
        "input_rect",
    ]:
        value = layout[key]
        if isinstance(value, dict):
            result[key] = [int(value["left"]), int(value["top"]), int(value["right"]), int(value["bottom"])]
        else:
            result[key] = [int(item) for item in value]
    result["confidence"] = float(layout.get("confidence", 0.9))
    result["source"] = str(layout.get("source", "calibrated"))
    result["reason"] = str(layout.get("reason", "exported replay sample"))
    return result


def _safe_sample_name(value: str) -> str:
    result = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in value.strip()).strip("_")
    if not result:
        raise ValueError("sample name cannot be empty")
    return result[:80]


if __name__ == "__main__":
    raise SystemExit(main())
