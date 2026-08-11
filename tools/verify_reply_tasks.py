from __future__ import annotations

import os
import shutil
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "reply_tasks_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")

from PySide6.QtCore import QCoreApplication

from whochat.ai.models import ReplyContext, ReplyGenerationResult, ReplySuggestion
from whochat.config import AppConfig
from whochat.core.models import ContactStatus, Message, Speaker, utc_now_iso
from whochat.core.runtime import PageClassification, PageType, missing_runtime_state
from whochat.services.bootstrap import build_services
from whochat.services.reply import ReplyGenerationService
from whochat.services.reply_tasks import ReplyTaskService


class SlowGenerator:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, context: ReplyContext, config: AppConfig) -> ReplyGenerationResult:
        self.calls += 1
        time.sleep(0.25)
        return ReplyGenerationResult(
            True,
            "slow_generated",
            [ReplySuggestion("稳妥版", "我确认后尽快回复你。", "low", "verify async")],
            config.ai.provider,
        )


def main() -> int:
    app = QCoreApplication.instance() or QCoreApplication([])
    services = build_services()
    contact = services.contacts.create_or_get_by_display_name("Async Contact")
    contact = services.contacts.update_profile(contact.id, status=ContactStatus.CONFIRMED)
    services.messages.add_message(
        Message(
            id="async_message",
            contact_id=contact.id,
            speaker=Speaker.OTHER,
            text="今天能回复吗？",
            content_type="text",
            ocr_confidence=0.94,
            observed_at=utc_now_iso(),
            message_time=None,
            time_source="observed",
            partial=False,
            fingerprint="async_message_fp",
            source="verify",
        )
    )
    context = ReplyContext(
        runtime=replace(missing_runtime_state(), page=PageClassification(PageType.CHAT_DM, 0.9, "verify")),
        contact=contact,
        strategy=services.strategies.get(contact.strategy_id),
        messages=services.messages.list_for_contact(contact.id),
        memories=[],
    )
    config = AppConfig()
    slow = SlowGenerator()
    task_service = ReplyTaskService(ReplyGenerationService(services.generation_logs, slow))
    received = []
    discarded = []
    statuses = []
    task_service.result_ready.connect(received.append)
    task_service.result_discarded.connect(discarded.append)
    task_service.status_changed.connect(statuses.append)

    started = time.monotonic()
    job_id = task_service.submit(context, config)
    elapsed = time.monotonic() - started
    if job_id != 1 or elapsed > 0.15:
        raise RuntimeError(f"submit should return quickly, job={job_id}, elapsed={elapsed:.3f}")
    busy = task_service.submit(context, config)
    if busy is not None or discarded != ["reply_generation_busy"]:
        raise RuntimeError(f"running task should reject parallel submit: busy={busy}, discarded={discarded}")

    deadline = time.monotonic() + 5
    while not received and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)
    if not received:
        raise RuntimeError("reply task result signal was not emitted")
    task = received[0]
    if task.job_id != 1 or not task.result.allowed or task.result.status != "slow_generated":
        raise RuntimeError(f"unexpected task result: {task}")
    if slow.calls != 1:
        raise RuntimeError(f"generator should be called once, calls={slow.calls}")
    if not any(status.startswith("reply_started") for status in statuses) or not any(status.startswith("reply_finished") for status in statuses):
        raise RuntimeError(f"status signals missing: {statuses}")
    audits = services.generation_logs.tail(5)
    if not audits or audits[0].status != "slow_generated":
        raise RuntimeError("async reply generation did not write audit")
    print(f"job={task.job_id} statuses={len(statuses)} audits={len(audits)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
