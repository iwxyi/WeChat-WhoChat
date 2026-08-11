from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["WHOCHAT_DATA_DIR"] = str(ROOT / "tmp" / "pipeline_verify" / "data")
os.environ["WHOCHAT_DB_PATH"] = str(ROOT / "tmp" / "pipeline_verify" / "data" / "whochat.db")

from whochat.core.runtime import PageType
from whochat.ocr.engine import OcrEngine
from whochat.ocr.models import OcrResult
from whochat.platform.window_tracker import WindowInfo
from whochat.services.bootstrap import build_services
from whochat.services.pipeline import CapturePipelineService


class CountingOcrEngine(OcrEngine):
    name = "counting-ocr"

    def __init__(self) -> None:
        self.calls = 0

    def recognize(self, image_path: Path, layout) -> OcrResult:
        self.calls += 1
        return OcrResult(boxes=[], source_image=str(image_path), engine=self.name)


def main() -> int:
    services = build_services()
    state = services.runtime.update_from_window_info(
        WindowInfo(hwnd=501, title="微信", process_name="Weixin", rect=(0, 0, 1200, 800), visible=True)
    )
    if state.layout is None or not state.capture_decision.should_capture:
        raise RuntimeError("runtime state is not capturable")

    pipeline = CapturePipelineService(capture_func=_capture_variant("normal"))
    result = pipeline.run_sync(state)
    if result is None or result.page.page_type != PageType.CHAT_DM or len(result.messages) < 2:
        raise RuntimeError("pipeline did not produce parsed chat result")

    duplicate = CapturePipelineService(capture_func=_capture_variant("same"))
    first = duplicate.run_sync(state)
    if first is None:
        raise RuntimeError("first duplicate test run should succeed")
    second_duplicate = duplicate.run_sync(state)
    if second_duplicate is not None:
        raise RuntimeError(f"duplicate test should return None on repeated snapshot, got {second_duplicate}")
    time.sleep(0.05)
    if not (duplicate.last_discard_reason or "").startswith("duplicate_snapshot"):
        raise RuntimeError(f"duplicate snapshot was not discarded: {duplicate.last_discard_reason}")

    region_engine = CountingOcrEngine()
    region_duplicate = CapturePipelineService(ocr_engine=region_engine, capture_func=_capture_variant("left_changed"))
    first_region = region_duplicate.run_sync(state)
    if first_region is None:
        raise RuntimeError("first region duplicate test run should succeed")
    second_region = region_duplicate.run_sync(state)
    if second_region is not None:
        raise RuntimeError("left-only visual change should be skipped before OCR")
    if region_engine.calls != 2:
        raise RuntimeError(f"left-only duplicate should not call OCR again, got {region_engine.calls} calls")

    cache_engine = CountingOcrEngine()
    cache_duplicate = CapturePipelineService(ocr_engine=cache_engine, capture_func=_capture_variant("contact_cycle"))
    first_contact = cache_duplicate.run_sync(state)
    second_contact = cache_duplicate.run_sync(state)
    third_contact = cache_duplicate.run_sync(state)
    if first_contact is None or second_contact is None:
        raise RuntimeError("contact cache test should allow first two distinct contacts")
    if third_contact is not None:
        raise RuntimeError("returning to unchanged contact should be skipped from hash cache")
    if cache_engine.calls != 4:
        raise RuntimeError(f"cached contact duplicate should skip third OCR pair, got {cache_engine.calls} calls")

    failing = CapturePipelineService(capture_func=_capture_failure)
    failed = failing.run_sync(state)
    if failed is not None:
        raise RuntimeError(f"failed capture should return None, got {failed}")
    if not (failing.last_discard_reason or "").startswith("pipeline_failed"):
        raise RuntimeError(f"failed capture did not set discard reason: {failing.last_discard_reason}")

    stale = CapturePipelineService(capture_func=_capture_variant("stale"), executor=ThreadPoolExecutor(max_workers=2))
    first_job = stale.submit(state)
    second_job = stale.submit(state)
    if first_job is None or second_job is None:
        raise RuntimeError("stale test jobs were not submitted")
    time.sleep(1.0)
    if stale.last_result is None or stale.last_result.job_id != second_job:
        raise RuntimeError(f"latest job did not finish: result={stale.last_result} discard={stale.last_discard_reason} status={stale.last_status}")
    if stale.last_discard_reason not in {f"stale_result:{first_job}", "superseded_running_job"}:
        raise RuntimeError(f"stale result was not discarded: {stale.last_discard_reason}")

    services.runtime.apply_pipeline_result(result)
    if services.runtime.state.visible_message_count != len(result.messages):
        raise RuntimeError("runtime did not record pipeline message count")

    print(f"page={result.page.page_type.value} messages={len(result.messages)} hash={result.snapshot_hash}")
    print(
        f"duplicate_discard={duplicate.last_discard_reason} region_duplicate={region_duplicate.last_discard_reason} "
        f"cached_duplicate={cache_duplicate.last_discard_reason}"
    )
    print(f"failure_discard={failing.last_discard_reason}")
    print(f"stale_result={stale.last_result.job_id if stale.last_result else None} stale_discard={stale.last_discard_reason}")
    return 0


def _capture_variant(mode: str):
    counters = {"count": 0}

    def capture(_rect, output: Path) -> Path:
        counters["count"] += 1
        current = counters["count"]
        if mode == "stale" and current == 1:
            time.sleep(0.2)
        variant = "same" if mode == "same" else f"{mode}-{current}"
        if mode == "stale":
            _write_stale_image(output, current)
        elif mode == "left_changed":
            _write_synthetic_chat(output, "left-constant", sidebar_variant=current)
        elif mode == "contact_cycle":
            _write_synthetic_chat(output, "contact-a" if current != 2 else "contact-b")
        else:
            _write_synthetic_chat(output, variant)
        return output

    return capture


def _write_synthetic_chat(path: Path, variant: str, *, sidebar_variant: int = 0) -> None:
    base = "#f6f7f9" if not variant.endswith("-2") else "#eef6ff"
    image = Image.new("RGB", (1200, 800), base)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 72, 800), fill="#1f2933")
    sidebar_fill = "#ffffff" if sidebar_variant % 2 == 0 else "#fff7ed"
    draw.rectangle((72, 0, 390, 800), fill=sidebar_fill)
    draw.rectangle((390, 0, 1200, 64), fill="#ffffff")
    draw.rectangle((390, 64, 1200, 650), fill="#edf2f7")
    draw.rectangle((390, 650, 1200, 800), fill="#ffffff")
    draw.rounded_rectangle((458, 140, 760, 190), radius=8, fill="#ffffff", outline="#d9e2ec")
    draw.rounded_rectangle((800, 230, 1130, 282), radius=8, fill="#d7f5e8", outline="#b7e4d1")
    if variant.endswith("-2") or variant == "contact-b":
        draw.rectangle((390, 360, 1200, 650), fill="#dceafe")
    draw.text((420, 23), f"联系人 A {variant}", fill="#102a43")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _write_stale_image(path: Path, count: int) -> None:
    image = Image.new("RGB", (1200, 800), "#ffffff")
    draw = ImageDraw.Draw(image)
    if count == 1:
        draw.rectangle((0, 0, 600, 800), fill="#000000")
    else:
        draw.rectangle((600, 0, 1200, 800), fill="#000000")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _capture_failure(_rect, _output: Path) -> Path:
    raise RuntimeError("verify capture failure")


if __name__ == "__main__":
    raise SystemExit(main())
