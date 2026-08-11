from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "ingestion_diagnostics_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_CONFIG_DIR"] = str(DATA_DIR / "config")
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from whochat.app import create_app
from whochat.core.models import Speaker, utc_now_iso
from whochat.core.runtime import PageClassification, PageType
from whochat.ocr.models import OcrRegion, OcrResult, OcrTextBox, ParsedOcrMessage
from whochat.platform.window_tracker import WindowInfo
from whochat.services.bootstrap import build_services
from whochat.services.pipeline import PipelineResult
from whochat.ui.main_window import MainWindow


def main() -> int:
    app = create_app()
    services = build_services()
    state = services.runtime.update_from_window_info(
        WindowInfo(hwnd=9301, title="微信", process_name="Weixin", rect=(0, 0, 1200, 800), visible=True)
    )
    if state.layout is None:
        raise RuntimeError("expected layout")
    window = MainWindow(services)

    missing_title = _result(
        state.layout,
        boxes=[
            OcrTextBox("微信", _inside(state.layout.title_rect, 0.05, 0.2, 0.18, 0.72), 0.91, OcrRegion.UNKNOWN, "verify"),
            OcrTextBox("消息内容", _inside(state.layout.message_rect, 0.08, 0.15, 0.35, 0.24), 0.86, OcrRegion.UNKNOWN, "verify"),
        ],
    )
    services.ingestion.ingest_pipeline_result(missing_title)
    missing_text = window._format_runtime_state(services.runtime.state)
    if "contact_ingestion=accepted:False" not in missing_text:
        raise RuntimeError(f"missing title diagnostic did not expose rejected ingestion: {missing_text}")
    if "contact_title_unavailable" not in missing_text or "重新校准顶部标题区" not in missing_text:
        raise RuntimeError(f"missing title diagnostic lacks actionable guidance: {missing_text}")

    accepted = _result(
        state.layout,
        job_id=2,
        boxes=[
            OcrTextBox("诊断联系人", _inside(state.layout.title_rect, 0.05, 0.2, 0.28, 0.72), 0.92, OcrRegion.UNKNOWN, "verify"),
            OcrTextBox("帮我确认下进度", _inside(state.layout.message_rect, 0.08, 0.15, 0.42, 0.24), 0.88, OcrRegion.UNKNOWN, "verify"),
            OcrTextBox("我稍后给你答复", _inside(state.layout.message_rect, 0.58, 0.34, 0.94, 0.43), 0.86, OcrRegion.UNKNOWN, "verify"),
        ],
        messages=[
            ParsedOcrMessage(Speaker.OTHER, "帮我确认下进度", _inside(state.layout.message_rect, 0.08, 0.15, 0.42, 0.24), 0.88, False, "verify"),
            ParsedOcrMessage(Speaker.ME, "我稍后给你答复", _inside(state.layout.message_rect, 0.58, 0.34, 0.94, 0.43), 0.86, False, "verify"),
        ],
    )
    services.ingestion.ingest_pipeline_result(accepted)
    accepted_text = window._format_runtime_state(services.runtime.state)
    if "contact_ingestion=accepted:True" not in accepted_text or "wechat/诊断联系人/suspected" not in accepted_text:
        raise RuntimeError(f"accepted contact diagnostic missing contact identity: {accepted_text}")
    if "确认联系人、分组和云端授权" not in accepted_text:
        raise RuntimeError(f"accepted contact diagnostic lacks next action: {accepted_text}")

    print("ingestion_diagnostics=ok")
    window.close()
    app.quit()
    return 0


def _result(layout, *, job_id: int = 1, boxes: list[OcrTextBox], messages: list[ParsedOcrMessage] | None = None) -> PipelineResult:
    return PipelineResult(
        job_id=job_id,
        hwnd=9301,
        target_app="wechat",
        app_label="微信",
        snapshot_hash=f"hash-{job_id}",
        image_path=DATA_DIR / f"capture-{job_id}.png",
        ocr_image_path=DATA_DIR / f"capture-{job_id}_content.png",
        crop_rect=None,
        layout=layout,
        ocr_result=OcrResult(boxes=boxes, source_image=str(DATA_DIR / f"capture-{job_id}.png"), engine="verify-ocr"),
        page=PageClassification(PageType.CHAT_DM, 0.76, "verify chat page"),
        messages=messages or [],
        created_at=utc_now_iso(),
    )


def _inside(rect, left: float, top: float, right: float, bottom: float):
    from whochat.core.runtime import Rect

    return Rect(
        rect.left + round(rect.width * left),
        rect.top + round(rect.height * top),
        rect.left + round(rect.width * right),
        rect.top + round(rect.height * bottom),
    )


if __name__ == "__main__":
    raise SystemExit(main())
