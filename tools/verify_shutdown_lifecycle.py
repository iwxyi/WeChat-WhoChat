from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "shutdown_lifecycle_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from whochat.ai.models import ReplyContext, ReplyGenerationResult
from whochat.config import AppConfig
from whochat.core.runtime import LayoutRegions, missing_runtime_state
from whochat.ocr.engine import OcrEngine
from whochat.ocr.models import OcrResult
from whochat.services.bootstrap import build_services
from whochat.services.pipeline import CapturePipelineService
from whochat.services.reply import ReplyGenerationService
from whochat.services.reply_tasks import ReplyTaskService
from whochat.storage.repositories import GenerationLogRepository


class ShutdownOcr(OcrEngine):
    name = "shutdown-ocr"

    def __init__(self) -> None:
        self.closed = False

    def recognize(self, image_path: Path, layout: LayoutRegions) -> OcrResult:
        return OcrResult([], str(image_path), self.name)

    def shutdown(self) -> None:
        self.closed = True


class ShutdownExecutor:
    def __init__(self) -> None:
        self.closed = False
        self.wait = None
        self.cancel_futures = None

    def submit(self, *_args, **_kwargs):
        raise RuntimeError("submit should not be used in lifecycle verify")

    def shutdown(self, *, wait: bool = True, cancel_futures: bool = False) -> None:
        self.closed = True
        self.wait = wait
        self.cancel_futures = cancel_futures


class NoopGenerator(ReplyGenerationService):
    def __init__(self, logs: GenerationLogRepository) -> None:
        super().__init__(logs)

    def generate(self, context: ReplyContext, config: AppConfig) -> ReplyGenerationResult:
        return ReplyGenerationResult(False, "verify", [], config.ai.provider)


def main() -> int:
    services = build_services()

    ocr = ShutdownOcr()
    capture_executor = ShutdownExecutor()
    pipeline = CapturePipelineService(ocr_engine=ocr, executor=capture_executor)
    pipeline.shutdown()
    if not ocr.closed or not capture_executor.closed or capture_executor.wait is not False or capture_executor.cancel_futures is not True:
        raise RuntimeError("capture pipeline did not shut down OCR engine and executor")
    if pipeline.last_status != "pipeline_shutdown":
        raise RuntimeError(f"pipeline status not updated: {pipeline.last_status}")

    reply_executor = ShutdownExecutor()
    reply_tasks = ReplyTaskService(NoopGenerator(services.generation_logs), executor=reply_executor)
    reply_tasks.shutdown()
    if not reply_executor.closed or reply_executor.wait is not False or reply_executor.cancel_futures is not True:
        raise RuntimeError("reply task executor was not shut down")
    if reply_tasks.last_status != "reply_shutdown":
        raise RuntimeError(f"reply status not updated: {reply_tasks.last_status}")

    services.autocapture.set_enabled(True)
    services.shutdown()
    if services.autocapture.enabled:
        raise RuntimeError("AppServices.shutdown should disable auto capture")
    if services.pipeline.last_status != "pipeline_shutdown" or services.reply_tasks.last_status != "reply_shutdown":
        raise RuntimeError("AppServices.shutdown did not propagate service shutdown")
    if not any(item.event == "services_shutdown" for item in services.logs.tail(10)):
        raise RuntimeError("services shutdown audit log missing")

    # Shutdown is intentionally idempotent because Qt aboutToQuit can be reached from multiple paths.
    services.shutdown()
    print(
        f"pipeline={pipeline.last_status} reply={reply_tasks.last_status} "
        f"app_pipeline={services.pipeline.last_status} app_reply={services.reply_tasks.last_status}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
