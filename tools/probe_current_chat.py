from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from whochat.capture.screenshot import capture_rect
from whochat.config import ConfigStore, OcrConfig, default_target_windows
from whochat.ocr.parser import classify_page_from_ocr, normalize_ocr_regions, parse_visible_messages
from whochat.platform.adapters import WeChatAdapter
from whochat.platform.window_tracker import diagnose_target_windows, find_target_windows, foreground_window_handle
from whochat.services.ingestion import extract_title_candidates
from whochat.services.pipeline import (
    PipelineResult,
    _merge_ocr_results,
    _offset_ocr_result,
    _prepare_ocr_input,
    _prepare_title_ocr_input,
)


def main() -> int:
    args = _parse_args()
    if args.wait_seconds > 0:
        print(f"waiting={args.wait_seconds}s switch_to_target_window_now")
        time.sleep(args.wait_seconds)
    config = ConfigStore().load()
    targets = [target for target in config.targets if target.enabled] or default_target_windows()
    windows = [window for window in find_target_windows(targets) if window.visible and window.foreground]
    if not windows:
        foreground = foreground_window_handle()
        print("status=blocked")
        print("reason=no foreground enabled target window")
        print(f"foreground_hwnd={foreground or '-'}")
        if foreground is None:
            print("window_api=desktop_api_unavailable_or_no_foreground")
        for item in diagnose_target_windows(targets, limit=12):
            print(
                "candidate="
                f"hwnd:{item.hwnd} foreground:{item.foreground} matched:{item.matched} "
                f"target:{item.target_app or '-'} label:{item.app_label or '-'} "
                f"reason:{item.reason} process:{item.process_name or '-'} title:{item.title!r}"
            )
        return 0

    window = max(windows, key=lambda item: (item.rect[2] - item.rect[0]) * (item.rect[3] - item.rect[1]))
    adapter = WeChatAdapter()
    snapshot = adapter.window_snapshot(window)
    layout = adapter.estimate_layout(snapshot)
    if layout is None or snapshot.rect is None:
        print("status=blocked")
        print(f"reason=layout_unavailable title={window.title!r} rect={window.rect}")
        return 0

    out_dir = ROOT / "tmp" / "probe"
    image_path = capture_rect(snapshot.rect.as_tuple(), out_dir / "current_chat.png")
    title_image_path, title_layout, title_offset, title_crop_rect = _prepare_title_ocr_input(image_path, layout)
    ocr_config = OcrConfig(
        provider=args.provider,
        language=args.language,
        min_confidence=args.min_confidence,
        use_gpu=args.use_gpu,
    )
    from whochat.ocr.engine import create_ocr_engine

    engine = create_ocr_engine(ocr_config)

    title_started = time.monotonic()
    title_result = _offset_ocr_result(engine.recognize(title_image_path, title_layout), title_offset)
    title_elapsed_ms = _elapsed_ms(title_started)
    title_probe = _minimal_result(window, image_path, title_image_path, title_crop_rect, layout, title_result)
    title_candidates = extract_title_candidates(title_result, title_probe, min_confidence=args.min_confidence)

    page_type = "-"
    message_count = "-"
    content_elapsed_ms = "-"
    if args.messages:
        content_image_path, content_layout, content_offset, _content_crop_rect = _prepare_ocr_input(image_path, layout)
        content_started = time.monotonic()
        content_result = _offset_ocr_result(engine.recognize(content_image_path, content_layout), content_offset)
        content_elapsed_ms = str(_elapsed_ms(content_started))
        merged = normalize_ocr_regions(_merge_ocr_results(title_result, content_result), layout)
        page = classify_page_from_ocr(merged, layout)
        page_type = page.page_type.value
        message_count = str(len(parse_visible_messages(merged, layout)))

    print("status=ok")
    print(f"target={window.target_app} label={window.app_label} hwnd={window.hwnd} process={window.process_name}")
    print(f"title={window.title!r} rect={window.rect} layout_source={layout.source.value} layout_confidence={layout.confidence}")
    print(f"screenshot={image_path}")
    print(f"title_crop={title_image_path} rect={title_crop_rect.as_tuple() if title_crop_rect else '-'}")
    print(f"ocr_provider={engine.name} title_elapsed_ms={title_elapsed_ms} warning={title_result.warning or '-'}")
    print(f"title_boxes={len(title_result.boxes)} title_candidates={len(title_candidates)}")
    if not args.redact and title_candidates:
        print("title_candidate=" + title_candidates[0])
    print(f"page_type={page_type} message_count={message_count} content_elapsed_ms={content_elapsed_ms}")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe the current foreground chat window with OCR diagnostics.")
    parser.add_argument("--provider", default="PaddleOCR")
    parser.add_argument("--language", default="ch")
    parser.add_argument("--min-confidence", type=float, default=0.5)
    parser.add_argument("--use-gpu", action="store_true")
    parser.add_argument("--messages", action="store_true", help="Also OCR the content area and parse visible messages.")
    parser.add_argument("--redact", action="store_true", help="Do not print recognized title text.")
    parser.add_argument("--wait-seconds", type=int, default=0, help="Wait before probing so you can focus a chat window.")
    return parser.parse_args()


def _minimal_result(window, image_path: Path, ocr_image_path: Path, crop_rect, layout, ocr_result) -> PipelineResult:
    return PipelineResult(
        job_id=0,
        hwnd=window.hwnd,
        target_app=window.target_app,
        app_label=window.app_label,
        snapshot_hash="probe",
        image_path=image_path,
        ocr_image_path=ocr_image_path,
        crop_rect=crop_rect,
        layout=layout,
        ocr_result=ocr_result,
        page=classify_page_from_ocr(ocr_result, layout),
        messages=[],
        created_at="probe",
    )


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


if __name__ == "__main__":
    raise SystemExit(main())
