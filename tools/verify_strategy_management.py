from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "tmp" / "strategy_management_verify"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.environ["WHOCHAT_DATA_DIR"] = str(DATA_DIR)
os.environ["WHOCHAT_CONFIG_DIR"] = str(DATA_DIR / "config")
os.environ["WHOCHAT_DB_PATH"] = str(DATA_DIR / "whochat.db")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from whochat.app import create_app
from whochat.core.models import ContactStatus
from whochat.services.bootstrap import build_services
from whochat.ui.main_window import MainWindow


def main() -> int:
    app = create_app()
    services = build_services()
    custom = services.strategies.create(
        name="归档验证分组",
        goal="验证用户可以收起不再使用的目标策略",
        mode="验证",
        tone="清楚、克制",
        avoid="含糊",
        reply_variants="稳妥版,简短版",
        requires_manual_reply=False,
    )
    contact = services.contacts.create_or_get_by_display_name("策略验证联系人")
    services.contacts.update_profile(contact.id, status=ContactStatus.CONFIRMED, strategy_id=custom.id)
    assigned = services.strategies.count_assigned_contacts(custom.id)
    if assigned != 1:
        raise RuntimeError(f"expected one assigned contact, got {assigned}")

    archived = services.strategies.set_archived(custom.id, True)
    if not archived.archived:
        raise RuntimeError("strategy archive flag was not persisted")
    if custom.id in {item.id for item in services.strategies.list_active()}:
        raise RuntimeError("archived strategy should be hidden from active list")
    if custom.id not in {item.id for item in services.strategies.list_all(include_archived=True)}:
        raise RuntimeError("archived strategy should remain available for history")
    try:
        services.strategies.set_archived("manual_protect", True)
    except ValueError:
        pass
    else:
        raise RuntimeError("manual protection strategy must not be archivable")

    restored = services.strategies.set_archived(custom.id, False)
    if restored.archived:
        raise RuntimeError("strategy restore failed")

    window = MainWindow(services)
    window._strategy_search.setText("归档验证")
    window._reload_strategy_table()
    if window._strategy_table.rowCount() != 1:
        raise RuntimeError(f"strategy search should show one row, got {window._strategy_table.rowCount()}")
    services.strategies.set_archived(custom.id, True)
    window._strategy_show_archived.setChecked(False)
    window._reload_strategy_table()
    if window._strategy_table.rowCount() != 0:
        raise RuntimeError("archived strategy should be hidden when filter is off")
    window._strategy_show_archived.setChecked(True)
    window._reload_strategy_table()
    if window._strategy_table.rowCount() != 1:
        raise RuntimeError("archived strategy should be visible when filter is on")

    print(f"strategy={custom.id} assigned={assigned} archived_filter_ok=True")
    window.close()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
