from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "memory_review_sync_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_CONFIG_DIR"] = str(DATA_DIR / "config")
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from whochat.app import create_app
from whochat.core.models import ContactStatus, MemoryKind, MemoryStatus
from whochat.services.bootstrap import build_services
from whochat.ui.floating_widget import FloatingWidget
from whochat.ui.main_window import MainWindow


def main() -> int:
    app = create_app()
    services = build_services()
    contact = services.contacts.create_or_get_by_display_name("记忆审核联系人")
    contact = services.contacts.update_profile(contact.id, status=ContactStatus.CONFIRMED)
    confirm_memory = services.memories.add_pending(contact.id, MemoryKind.FACT, "确认后应进入长期画像", 0.93)
    reject_memory = services.memories.add_pending(contact.id, MemoryKind.AVOID, "拒绝后仍应可审计", 0.31)

    window = MainWindow(services)
    floating = FloatingWidget()
    window.attach_floating_widget(floating)
    window._reload_contact_list(contact.id)
    window._render_contact_detail(contact)
    window._select_page("memories")

    window._set_memory_status(confirm_memory.id, MemoryStatus.CONFIRMED)
    overview = window._overview_contact_notes.toPlainText()
    detail = window._contact_memory_text.toPlainText()
    if "[confirmed/fact] 确认后应进入长期画像" not in overview:
        raise RuntimeError(f"confirmed memory did not refresh overview: {overview}")
    if "[confirmed/fact] 确认后应进入长期画像" not in detail:
        raise RuntimeError(f"confirmed memory did not refresh contact detail: {detail}")
    if window._memory_tabs.currentIndex() != 0:
        raise RuntimeError("memory review tab should keep current index after refresh")

    window._set_memory_status(reject_memory.id, MemoryStatus.REJECTED)
    detail = window._contact_memory_text.toPlainText()
    if "[rejected/avoid] 拒绝后仍应可审计" not in detail:
        raise RuntimeError(f"rejected memory did not refresh contact detail: {detail}")
    pending_ids = {memory.id for memory in services.memories.list_by_status(MemoryStatus.PENDING)}
    if confirm_memory.id in pending_ids or reject_memory.id in pending_ids:
        raise RuntimeError("reviewed memories should leave pending list")
    if "记忆已更新为：rejected" not in window.statusBar().currentMessage():
        raise RuntimeError(f"memory status feedback missing: {window.statusBar().currentMessage()}")

    print(f"confirmed={confirm_memory.id[:12]} rejected={reject_memory.id[:12]} pending={len(pending_ids)}")
    floating.close()
    window.close()
    services.shutdown()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
