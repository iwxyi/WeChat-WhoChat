from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
import json
from pathlib import Path
import re
import shutil

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from whochat.ai.models import ReplyContext, ReplyGenerationResult, ReplySuggestion
from whochat.ai.generator import test_ai_connection
from whochat.ai.prompt import PromptPreview, build_prompt_preview
from whochat.config import AppConfig, ConfigStore, TargetWindowConfig
from whochat.capture.screenshot import capture_rect
from whochat.core.models import Contact, ContactStatus, ConversationType, IdentityStatus, Memory, MemoryKind, MemoryStatus, Strategy
from whochat.core.models import utc_now_iso
from whochat.core.runtime import LayoutRegions, Rect, RuntimeState, TargetApp, ThemeMode
from whochat.core.paths import app_data_dir
from whochat.diagnostics import diagnostics_log_path
from whochat.ocr.engine import PreviewOcrEngine, create_ocr_engine
from whochat.ocr.models import OcrResult
from whochat.ocr.parser import classify_page_from_ocr, parse_visible_messages
from whochat.platform.window_tracker import diagnose_target_windows, foreground_window_handle
from whochat.security.redaction import redact_diagnostics_payload, redact_diagnostics_text
from whochat.services.bootstrap import AppServices, build_services
from whochat.services.reply_tasks import ReplyTaskResult
from whochat.services.reply import context_hash as _reply_context_hash
from whochat.services.status import build_status_chain
from whochat.ui.calibration_overlay import CalibrationCanvas


@dataclass(frozen=True)
class NavItem:
    key: str
    title: str
    subtitle: str


NAV_ITEMS = [
    NavItem("overview", "总览", "当前状态与建议"),
    NavItem("contacts", "聊天对象", "私聊、群聊与画像"),
    NavItem("strategies", "分组", "目标与语气策略"),
    NavItem("memories", "记忆", "摘要与待确认信息"),
    NavItem("settings", "设置", "AI、隐私与采集"),
    NavItem("diagnostics", "诊断", "日志与识别调试"),
]


class StrategyDialog(QDialog):
    def __init__(self, parent: QWidget, strategy: Strategy | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑分组策略" if strategy else "新增分组策略")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        form = QGridLayout()
        self.name = QLineEdit(strategy.name if strategy else "")
        self.goal = QTextEdit(strategy.goal if strategy else "")
        self.goal.setMinimumHeight(88)
        self.mode = QLineEdit(strategy.mode if strategy else "")
        self.tone = QLineEdit(strategy.tone if strategy else "")
        self.avoid = QTextEdit(strategy.avoid if strategy else "")
        self.avoid.setMinimumHeight(68)
        self.reply_variants = QLineEdit(strategy.reply_variants if strategy else "稳妥版,简短版,推进版")
        self.requires_manual_reply = QCheckBox("只整理信息，不生成可直接复制的自动回复")
        self.requires_manual_reply.setChecked(strategy.requires_manual_reply if strategy else False)

        fields: list[tuple[str, QWidget]] = [
            ("分组名称", self.name),
            ("目标", self.goal),
            ("模式", self.mode),
            ("语气", self.tone),
            ("禁忌", self.avoid),
            ("回复变体", self.reply_variants),
            ("保护", self.requires_manual_reply),
        ]
        for row, (label, widget) in enumerate(fields):
            form.addWidget(QLabel(label), row, 0, Qt.AlignmentFlag.AlignTop)
            form.addWidget(widget, row, 1)
        form.setColumnStretch(1, 1)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> dict:
        return {
            "name": self.name.text().strip(),
            "goal": self.goal.toPlainText().strip(),
            "mode": self.mode.text().strip() or "自定义",
            "tone": self.tone.text().strip() or "自然、清晰",
            "avoid": self.avoid.toPlainText().strip(),
            "reply_variants": self.reply_variants.text().strip(),
            "requires_manual_reply": self.requires_manual_reply.isChecked(),
        }

    def _accept_if_valid(self) -> None:
        values = self.values()
        if not values["name"] or not values["goal"]:
            self.parentWidget().statusBar().showMessage("分组名称和目标不能为空", 3000)
            return
        self.accept()


class CalibrationDialog(QDialog):
    def __init__(self, parent: QWidget, layout: LayoutRegions, screenshot_path: Path | None = None) -> None:
        super().__init__(parent)
        self._layout = layout
        self._screenshot_path = screenshot_path
        self._ocr_engine = PreviewOcrEngine()
        self._ocr_result: OcrResult | None = None
        self.setWindowTitle("区域校准")
        self.setMinimumSize(960, 820)
        body = QVBoxLayout(self)
        body.setContentsMargins(18, 18, 18, 18)
        body.setSpacing(12)

        hint = QLabel("拖动截图上的区域或微调比例。保存后只记录相对窗口比例，不默认保存截图样本。")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        body.addWidget(hint)

        pixmap = QPixmap(str(screenshot_path)) if screenshot_path and screenshot_path.exists() else QPixmap()
        self.canvas = CalibrationCanvas(layout, pixmap if not pixmap.isNull() else None)
        self.canvas.setFixedHeight(320)
        self.canvas.layout_changed.connect(self._sync_spins_from_canvas)
        body.addWidget(self.canvas, 1)

        form = QGridLayout()
        self.name = QLineEdit("微信默认校准")
        self.nav_right = _ratio_spin(_ratio(layout.window_rect, layout.nav_rect.right, "x"))
        self.chat_list_right = _ratio_spin(_ratio(layout.window_rect, layout.chat_list_rect.right, "x"))
        self.title_bottom = _ratio_spin(_ratio(layout.window_rect, layout.title_rect.bottom, "y"))
        self.input_top = _ratio_spin(_ratio(layout.window_rect, layout.input_rect.top, "y"))
        self.theme = QComboBox()
        self.theme.addItems([ThemeMode.UNKNOWN.value, ThemeMode.LIGHT.value, ThemeMode.DARK.value])

        rows: list[tuple[str, QWidget]] = [
            ("名称", self.name),
            ("左侧导航右边界", self.nav_right),
            ("聊天列表右边界", self.chat_list_right),
            ("标题栏下边界", self.title_bottom),
            ("输入区上边界", self.input_top),
            ("主题", self.theme),
        ]
        for row, (label, widget) in enumerate(rows):
            form.addWidget(QLabel(label), row, 0)
            form.addWidget(widget, row, 1)
        body.addLayout(form)

        preview = QTextEdit()
        preview.setReadOnly(True)
        preview.setMinimumHeight(110)
        self.preview = preview
        body.addWidget(preview)
        for widget in [self.nav_right, self.chat_list_right, self.title_bottom, self.input_top]:
            widget.valueChanged.connect(self._refresh_preview)
        self._refresh_ocr_preview(layout)
        self._refresh_preview()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        body.addWidget(buttons)

    def calibrated_layout(self) -> LayoutRegions:
        window = self.canvas.layout_regions.window_rect
        nav_right = _absolute_x(window, self.nav_right.value())
        chat_list_right = _absolute_x(window, self.chat_list_right.value())
        title_bottom = _absolute_y(window, self.title_bottom.value())
        input_top = _absolute_y(window, self.input_top.value())
        nav = Rect(window.left, window.top, nav_right, window.bottom)
        chat_list = Rect(nav_right, window.top, chat_list_right, window.bottom)
        content = Rect(chat_list_right, window.top, window.right, window.bottom)
        title = Rect(content.left, content.top, content.right, title_bottom)
        input_rect = Rect(content.left, input_top, content.right, window.bottom)
        message = Rect(content.left, title.bottom, content.right, input_rect.top)
        return LayoutRegions(
            window_rect=window,
            nav_rect=nav,
            chat_list_rect=chat_list,
            content_rect=content,
            title_rect=title,
            message_rect=message,
            input_rect=input_rect,
            confidence=0.92,
            source=self._layout.source,
            reason="用户手动校准预览",
        )

    def values(self) -> dict:
        return {
            "name": self.name.text().strip() or "微信校准",
            "theme": ThemeMode(self.theme.currentText()),
            "layout": self.calibrated_layout(),
        }

    def _refresh_preview(self) -> None:
        layout = self.calibrated_layout()
        self.canvas.blockSignals(True)
        self.canvas.set_layout_regions(layout)
        self.canvas.blockSignals(False)
        self._refresh_ocr_preview(layout)
        self.preview.setText(
            "\n".join(
                [
                    f"nav={layout.nav_rect.as_tuple()}",
                    f"chat_list={layout.chat_list_rect.as_tuple()}",
                    f"message={layout.message_rect.as_tuple()}",
                    f"input={layout.input_rect.as_tuple()}",
                    "",
                    *self._ocr_summary_lines(),
                ]
            )
        )

    def _sync_spins_from_canvas(self, layout: LayoutRegions) -> None:
        self._set_spin_without_signal(self.nav_right, _ratio(layout.window_rect, layout.nav_rect.right, "x"))
        self._set_spin_without_signal(self.chat_list_right, _ratio(layout.window_rect, layout.chat_list_rect.right, "x"))
        self._set_spin_without_signal(self.title_bottom, _ratio(layout.window_rect, layout.title_rect.bottom, "y"))
        self._set_spin_without_signal(self.input_top, _ratio(layout.window_rect, layout.input_rect.top, "y"))
        self._refresh_ocr_preview(layout)
        self.preview.setText(
            "\n".join(
                [
                    f"nav={layout.nav_rect.as_tuple()}",
                    f"chat_list={layout.chat_list_rect.as_tuple()}",
                    f"message={layout.message_rect.as_tuple()}",
                    f"input={layout.input_rect.as_tuple()}",
                    "",
                    *self._ocr_summary_lines(),
                ]
            )
        )

    def _refresh_ocr_preview(self, layout: LayoutRegions) -> None:
        if not self._screenshot_path:
            self._ocr_result = None
            self.canvas.set_ocr_result(None)
            return
        self._ocr_result = self._ocr_engine.recognize(self._screenshot_path, layout)
        self.canvas.set_ocr_result(self._ocr_result)

    def _ocr_summary_lines(self) -> list[str]:
        if not self._ocr_result:
            return ["ocr_preview=unavailable"]
        page = classify_page_from_ocr(self._ocr_result, self.canvas.layout_regions)
        messages = parse_visible_messages(self._ocr_result, self.canvas.layout_regions)
        return [
            *self._ocr_result.summary_lines(8),
            f"page_preview={page.page_type.value} confidence={page.confidence:.2f}",
            *[f"message_preview={item.speaker.value} {item.confidence:.2f} partial={item.partial} {item.text}" for item in messages[:4]],
        ]

    def _set_spin_without_signal(self, spin: QDoubleSpinBox, value: float) -> None:
        spin.blockSignals(True)
        spin.setValue(max(0.0, min(value, 1.0)))
        spin.blockSignals(False)

    def _accept_if_valid(self) -> None:
        layout = self.calibrated_layout()
        if layout.nav_rect.width < 32 or layout.chat_list_rect.width < 120 or layout.message_rect.width < 240:
            self.parentWidget().statusBar().showMessage("区域过窄，请检查分割线比例", 3000)
            return
        if layout.title_rect.height < 32 or layout.input_rect.height < 60 or layout.message_rect.height < 160:
            self.parentWidget().statusBar().showMessage("标题、消息或输入区域高度不合理", 3000)
            return
        self.accept()


class TargetAppDialog(QDialog):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("新增目标应用")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        form = QGridLayout()
        self.label = QLineEdit()
        self.process_names = QLineEdit()
        self.title_keywords = QLineEdit()
        self.exclude_title_keywords = QLineEdit()
        for row, (label, widget) in enumerate([
            ("显示名", self.label),
            ("进程名", self.process_names),
            ("标题关键词", self.title_keywords),
            ("排除标题", self.exclude_title_keywords),
        ]):
            form.addWidget(QLabel(label), row, 0)
            form.addWidget(widget, row, 1)
        form.setColumnStretch(1, 1)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> dict:
        label = self.label.text().strip()
        return {
            "app_id": _target_app_id(label),
            "label": label,
            "process_names": _split_match_rules(self.process_names.text()),
            "title_keywords": _split_match_rules(self.title_keywords.text()),
            "exclude_title_keywords": _split_match_rules(self.exclude_title_keywords.text()),
        }

    def _accept_if_valid(self) -> None:
        values = self.values()
        if not values["label"]:
            self.parentWidget().statusBar().showMessage("目标应用显示名不能为空", 3000)
            return
        if not values["process_names"] and not values["title_keywords"]:
            self.parentWidget().statusBar().showMessage("至少填写一个进程名或标题关键词", 3000)
            return
        self.accept()


def _ratio(window: Rect, value: int, axis: str) -> float:
    if axis == "x":
        return (value - window.left) / max(1, window.width)
    return (value - window.top) / max(1, window.height)


def _absolute_x(window: Rect, ratio: float) -> int:
    return window.left + round(window.width * ratio)


def _absolute_y(window: Rect, ratio: float) -> int:
    return window.top + round(window.height * ratio)


def _ratio_spin(value: float) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(0.0, 1.0)
    spin.setDecimals(3)
    spin.setSingleStep(0.005)
    spin.setValue(max(0.0, min(value, 1.0)))
    return spin


def _days_spin(value: int) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(1, 365)
    spin.setSuffix(" 天")
    spin.setValue(max(1, min(int(value), 365)))
    return spin


def _split_match_rules(value: str) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in value.replace("；", ",").replace(";", ",").replace("\n", ",").split(","):
        cleaned = item.strip()
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def _target_app_id(label: str) -> str:
    value = re.sub(r"[^0-9A-Za-z]+", "_", label.strip().lower()).strip("_")
    return f"custom_{value or 'chat'}"


def _unique_target_app_id(base: str, existing: list[str]) -> str:
    used = set(existing)
    if base not in used:
        return base
    index = 2
    while f"{base}_{index}" in used:
        index += 1
    return f"{base}_{index}"


def _compact_table(table: QTableWidget) -> None:
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(24)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    table.setAlternatingRowColors(True)


def _tail_lines(path: Path, limit: int) -> list[str]:
    if not path.exists():
        return ["暂无"]
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:] or ["暂无"]
    except OSError as exc:
        return [f"读取失败：{exc}"]


def _format_app_log(item) -> str:
    return f"[{item.level}] {item.ts} {item.module}.{item.event}: {item.message}"


def _clip_debug_text(value: str, limit: int = 48) -> str:
    text = " ".join(value.strip().split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _avg_int(values: list[int]) -> str:
    return "-" if not values else str(round(sum(values) / len(values)))


def _avg_number(values: list[int]) -> float | None:
    return None if not values else sum(values) / len(values)


def _capture_perf_status(avg_total_ms: float | None) -> tuple[str, str]:
    if avg_total_ms is None:
        return "unknown", "等待更多采集样本"
    if avg_total_ms <= 15000:
        return "ok", "性能正常"
    if avg_total_ms <= 45000:
        return "warning", "偏慢；确认已启用标题/内容区裁剪并避免频繁滚动"
    return "slow", "过慢；建议保持 PaddleOCR worker 常驻、拉长自动 OCR 间隔或重新校准裁剪区域"


def _ingestion_action(accepted: bool, reason: str, has_contact: bool) -> str:
    if accepted and has_contact:
        return "在聊天对象页确认联系人、分组和云端授权"
    if reason.startswith("title_unavailable") or reason.startswith("contact_title_unavailable"):
        return "检查标题裁剪图和候选文本；必要时重新校准顶部标题区"
    if reason.startswith("title_ocr_warning") or reason.startswith("ocr_warning"):
        return "查看 ocr_worker 日志和 PaddleOCR 耗时；必要时等待熔断恢复或拉长间隔"
    if reason.startswith("page_blocked"):
        return "切回私聊或群聊页面，避免公众号、设置、搜索或文章页"
    return "查看标题 OCR、页面分类和最近日志定位阻断原因"


def _window_match_action(matched_foreground, foreground_excluded, matched_background: list) -> str:
    if matched_foreground is not None:
        return f"action=当前前台已命中：{matched_foreground.app_label}。可运行采集管线或等待自动采集。"
    if foreground_excluded is not None:
        return (
            f"action=当前前台是 {foreground_excluded.app_label} 的非聊天子窗口，"
            "已按排除规则暂停。关闭预览、设置或转发窗口，切回聊天主窗口。"
        )
    if matched_background:
        labels = ", ".join(f"{item.app_label}:{item.title}" for item in matched_background[:3])
        return f"action=发现已启用聊天窗口但不在前台：{labels}。切到目标聊天窗口后才会截图和 OCR。"
    return "action=发现相关窗口但未命中启用目标。检查进程名、标题关键词或排除标题设置。"


def _reply_evidence_summary(context: ReplyContext, result: ReplyGenerationResult) -> str:
    contact = f"{context.contact.platform}·{context.contact.display_name}" if context.contact else "未识别对象"
    strategy = context.strategy.name if context.strategy else "无分组"
    cloud = "允许云端" if context.contact and context.contact.allow_cloud_ai else "本地/未授权云端"
    return (
        f"依据：{contact}｜{strategy}｜消息 {len(context.messages)}｜记忆 {len(context.memories)}｜"
        f"{context.runtime.page.page_type.value}｜{cloud}｜{result.status}"
    )


def _reply_evidence_detail(context: ReplyContext, result: ReplyGenerationResult) -> str:
    contact = context.contact
    strategy = context.strategy
    return "\n".join(
        [
            f"allowed={result.allowed}",
            f"status={result.status}",
            f"provider={result.provider}",
            f"contact={contact.platform + '·' + contact.display_name if contact else '-'}",
            f"contact_status={contact.status.value if contact else '-'}",
            f"cloud_ai={contact.allow_cloud_ai if contact else False}",
            f"strategy={strategy.name if strategy else '-'}",
            f"manual_protection={strategy.requires_manual_reply if strategy else False}",
            f"page={context.runtime.page.page_type.value}/{context.runtime.page.confidence:.2f}",
            f"messages={len(context.messages)}",
            f"memories={len(context.memories)}",
        ]
    )


def _redacted_config_snapshot(config: AppConfig) -> dict:
    snapshot = asdict(config)
    api_key = snapshot.get("ai", {}).get("api_key", "")
    snapshot["ai"]["api_key"] = "<set>" if api_key else "<empty>"
    return snapshot


def _config_changes(before: dict, after: dict) -> dict:
    changes: dict[str, dict[str, object]] = {}

    def walk(prefix: str, left, right) -> None:
        if isinstance(left, dict) and isinstance(right, dict):
            keys = sorted(set(left) | set(right))
            for key in keys:
                path = f"{prefix}.{key}" if prefix else str(key)
                walk(path, left.get(key), right.get(key))
            return
        if left == right:
            return
        if prefix == "ai.api_key":
            changes[prefix] = {"old": "<changed>" if left != right else "<unchanged>", "new": "<changed>" if left != right else "<unchanged>"}
            return
        changes[prefix] = {"old": left, "new": right}

    walk("", before, after)
    return changes


def _status_reason_with_action(step) -> str:
    if not getattr(step, "action", ""):
        return step.reason
    if step.action in step.reason:
        return step.reason
    return f"{step.reason}｜建议：{step.action}"


def _primary_status_step(steps):
    for state in ["阻断", "失败", "退避"]:
        found = next((step for step in steps if step.state == state), None)
        if found is not None:
            return found
    found = next((step for step in steps if step.stage == "OCR" and step.state in {"运行中", "读取消息", "等待"}), None)
    if found is not None:
        return found
    found = next((step for step in steps if step.stage == "AI"), None)
    if found is not None:
        return found
    return steps[-1]


def _strategy_status_label(strategy: Strategy) -> str:
    prefix = "内置" if strategy.id in {"default", "manual_protect"} else "自定义"
    return f"{prefix} / 已归档" if strategy.archived else f"{prefix} / 启用"


def _contact_display_label(contact: Contact) -> str:
    platform = (contact.platform or "chat").strip()
    return f"{platform}·{contact.display_name}"


class MainWindow(QMainWindow):
    floating_visibility_changed = Signal(bool)
    targets_changed = Signal(object)

    def __init__(self, services: AppServices | None = None) -> None:
        super().__init__()
        self.setWindowTitle("WhoChat")
        self.resize(1280, 820)
        self.setMinimumSize(980, 640)
        self._services = services or build_services()
        self._floating = None
        self._config_store = ConfigStore()
        self._config = self._config_store.load()
        self._log_text: QTextEdit | None = None
        self._pending_logs: list[str] = []
        self._nav_buttons: dict[str, QPushButton] = {}
        self._pages = QStackedWidget()
        self._page_titles: dict[str, str] = {}
        self._ai_status_value: QLabel | None = None
        self._ai_health_label: QLabel | None = None
        self._page_status_value: QLabel | None = None
        self._page_status_subtitle: QLabel | None = None
        self._capture_status_value: QLabel | None = None
        self._capture_status_subtitle: QLabel | None = None
        self._runtime_text: QTextEdit | None = None
        self._environment_text: QTextEdit | None = None
        self._window_match_text: QTextEdit | None = None
        self._diagnostics_file_text: QTextEdit | None = None
        self._generation_log_text: QTextEdit | None = None
        self._log_level_filter: QComboBox | None = None
        self._contact_list: QListWidget | None = None
        self._contact_profile_text: QTextEdit | None = None
        self._contact_identity_text: QTextEdit | None = None
        self._contact_members_text: QTextEdit | None = None
        self._contact_chat_text: QTextEdit | None = None
        self._contact_memory_text: QTextEdit | None = None
        self._contact_feedback_text: QTextEdit | None = None
        self._overview_status_summary: QLabel | None = None
        self._overview_next_action: QLabel | None = None
        self._overview_next_action_meta: QLabel | None = None
        self._overview_status_table: QTableWidget | None = None
        self._overview_chat_table: QTableWidget | None = None
        self._overview_contact_values: dict[str, QLabel] = {}
        self._overview_contact_notes: QTextEdit | None = None
        self._strategy_table: QTableWidget | None = None
        self._strategy_search: QLineEdit | None = None
        self._strategy_show_archived: QCheckBox | None = None
        self._memory_tabs: QTabWidget | None = None
        self._suggestions_panel: QFrame | None = None
        self._suggestion_result: ReplyGenerationResult | None = None
        self._privacy_long_memory: QCheckBox | None = None
        self._privacy_debug_screenshots: QCheckBox | None = None
        self._privacy_trim_cloud: QCheckBox | None = None
        self._privacy_cloud_review: QCheckBox | None = None
        self._privacy_manual_blocks: QCheckBox | None = None
        self._privacy_log_retention: QSpinBox | None = None
        self._privacy_debug_retention: QSpinBox | None = None
        self._privacy_capture_retention: QSpinBox | None = None
        self._privacy_calibration_retention: QSpinBox | None = None
        self._privacy_feedback_retention: QSpinBox | None = None
        self._ai_request_cooldown: QSpinBox | None = None
        self._ai_dedupe_minutes: QSpinBox | None = None
        self._ai_daily_limit: QSpinBox | None = None
        self._ai_failure_threshold: QSpinBox | None = None
        self._ai_failure_backoff: QSpinBox | None = None
        self._ocr_provider: QComboBox | None = None
        self._ocr_language: QLineEdit | None = None
        self._ocr_min_confidence: QDoubleSpinBox | None = None
        self._ocr_use_gpu: QCheckBox | None = None
        self._capture_debounce: QSlider | None = None
        self._capture_debounce_label: QLabel | None = None
        self._capture_ocr_interval: QSpinBox | None = None
        self._capture_auto_enabled: QCheckBox | None = None
        self._capture_pause_unknown: QCheckBox | None = None
        self._capture_block_unconfirmed: QCheckBox | None = None
        self._floating_placement: QComboBox | None = None
        self._floating_opacity: QSpinBox | None = None
        self._floating_suggestion_count: QSpinBox | None = None
        self._target_checkboxes: dict[str, QCheckBox] = {}
        self._target_process_inputs: dict[str, QLineEdit] = {}
        self._target_title_inputs: dict[str, QLineEdit] = {}
        self._target_exclude_title_inputs: dict[str, QLineEdit] = {}
        self._target_grid: QGridLayout | None = None
        self._provider_health_timer = QTimer(self)
        self._provider_health_timer.setInterval(30000)
        self._provider_health_timer.timeout.connect(self._refresh_provider_health)
        self._services.runtime.capture_gate.policy = replace(
            self._services.runtime.capture_gate.policy,
            scroll_debounce_ms=self._config.capture.scroll_debounce_ms,
            ocr_min_interval_ms=self._config.capture.ocr_min_interval_ms,
        )
        self._services.autocapture.set_enabled(self._config.capture.auto_capture_enabled)

        root = QWidget()
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        shell.addWidget(self._build_sidebar())
        shell.addWidget(self._build_content(), 1)
        self.setCentralWidget(root)

        self._register_pages()
        self._select_page("overview")
        self._services.runtime.state_changed.connect(self.update_runtime_state)
        self._services.pipeline.title_ready.connect(self._on_pipeline_title_ready)
        self._services.pipeline.result_ready.connect(self._on_pipeline_result_ready)
        self._services.reply_tasks.result_ready.connect(self._on_reply_task_ready)
        self._services.reply_tasks.result_discarded.connect(self._on_reply_task_discarded)
        self._services.reply_tasks.status_changed.connect(self._on_reply_task_status_changed)
        self.append_log("app_started: WhoChat UI initialized")
        self.update_runtime_state(self._services.runtime.state)
        self._provider_health_timer.start()

    def append_log(self, message: str, level: str = "info") -> None:
        line = f"[{level}] {datetime.now().strftime('%H:%M:%S')} {message}"
        if hasattr(self, "_services"):
            try:
                self._services.logs.append(level, "ui", "ui_log", message)
            except Exception:
                pass
        if self._log_text is None:
            self._pending_logs.append(line)
            return
        if self._log_level_filter is not None and self._log_level_filter.currentText() != "全部":
            if level != self._log_level_filter.currentText():
                return
        self._log_text.append(line)

    def update_runtime_state(self, state: RuntimeState) -> None:
        if self._page_status_value is not None:
            self._page_status_value.setText(state.page.page_type.value)
        if self._page_status_subtitle is not None:
            title = state.window.title or "等待目标窗口"
            self._page_status_subtitle.setText(f"{state.status_label} · {title}")
        if self._capture_status_value is not None:
            self._capture_status_value.setText("允许" if state.capture_decision.should_capture else "暂停")
        if self._capture_status_subtitle is not None:
            self._capture_status_subtitle.setText(state.capture_decision.reason)
        if self._runtime_text is not None:
            self._runtime_text.setText(self._format_runtime_state(state))
        if self._window_match_text is not None:
            self._window_match_text.setText(self._format_window_match_diagnostics())
        if self._ai_health_label is not None:
            self._ai_health_label.setText(self._services.reply_generator.provider_health_summary())
        if self._diagnostics_file_text is not None:
            self._diagnostics_file_text.setText(self._format_diagnostics_files())
        self.pause_button.setText("继续采集" if state.paused else "暂停采集")
        self._refresh_overview_data()
        self._sync_floating_content()

    def _refresh_provider_health(self) -> None:
        before = self._services.reply_generator.provider_health_summary()
        after = self._services.reply_generator.refresh_provider_health()
        if self._ai_health_label is not None:
            self._ai_health_label.setText(after)
        if before != after:
            self.append_log(f"ai_provider_health_changed: {after}")
            self._refresh_overview_data()

    def _format_runtime_state(self, state: RuntimeState) -> str:
        window_rect = state.window.rect.as_tuple() if state.window.rect else None
        lines = [
            f"target={state.window.target.value}",
            f"window_state={state.window.state.value}",
            f"title={state.window.title or '-'}",
            f"process={state.window.process_name or '-'}",
            f"rect={window_rect}",
            f"window_diagnostic={state.window.diagnostic or '-'}",
            f"page={state.page.page_type.value} confidence={state.page.confidence:.2f}",
            f"page_reason={state.page.reason}",
            f"capture={state.capture_decision.should_capture} reason={state.capture_decision.reason}",
            f"paused={state.paused}",
            f"ocr_pending={state.ocr_pending}",
            f"pipeline_status={state.pipeline_status}",
            f"reply_running={self._services.reply_tasks.is_running}",
            f"reply_status={self._services.reply_tasks.last_status}",
            f"provider_health={self._services.reply_generator.provider_health_summary()}",
            f"snapshot_hash={state.last_snapshot_hash or '-'}",
            f"visible_message_count={state.visible_message_count}",
            self._format_title_ocr_state(),
            self._format_ingestion_state(),
        ]
        if state.layout:
            lines.extend(
                [
                    f"layout_source={state.layout.source.value} confidence={state.layout.confidence:.2f}",
                    f"chat_list_rect={state.layout.chat_list_rect.as_tuple()}",
                    f"message_rect={state.layout.message_rect.as_tuple()}",
                    f"input_rect={state.layout.input_rect.as_tuple()}",
                    f"layout_reason={state.layout.reason}",
                ]
            )
        return "\n".join(lines)

    def _format_title_ocr_state(self) -> str:
        title = self._services.pipeline.last_title_result
        if title is None:
            return "title_ocr=none"
        boxes = sorted(title.ocr_result.boxes, key=lambda box: (-box.confidence, box.rect.top, box.rect.left))
        candidates = [
            f"{box.confidence:.2f}:{_clip_debug_text(box.text, 28)}"
            for box in boxes[:5]
            if box.text.strip()
        ]
        warning = title.ocr_result.warning or "-"
        crop = title.title_crop_rect.as_tuple() if title.title_crop_rect else None
        return (
            f"title_ocr=job:{title.job_id} target:{title.target_app}/{title.app_label} "
            f"elapsed_ms:{title.elapsed_ms if title.elapsed_ms is not None else '-'} "
            f"warning:{warning} crop:{crop} candidates:{' | '.join(candidates) if candidates else '-'}"
        )

    def _format_ingestion_state(self) -> str:
        ingestion = self._services.ingestion.last_result
        if ingestion is None:
            return "contact_ingestion=none action:等待标题 OCR 或手动运行采集"
        contact = ingestion.contact
        contact_text = f"{contact.platform}/{contact.display_name}/{contact.status.value}" if contact else "-"
        candidates = " | ".join(_clip_debug_text(item, 36) for item in ingestion.title_candidates[:5])
        action = _ingestion_action(ingestion.accepted, ingestion.reason, contact is not None)
        return (
            f"contact_ingestion=accepted:{ingestion.accepted} reason:{ingestion.reason} "
            f"contact:{contact_text} inserted:{ingestion.inserted_messages} duplicate:{ingestion.duplicate_messages} "
            f"title_candidates:{candidates or '-'} action:{action}"
        )

    def attach_floating_widget(self, floating: QWidget) -> None:
        self._floating = floating
        if hasattr(floating, "apply_preferences"):
            floating.apply_preferences(
                placement_preference=self._config.floating.placement_preference,
                opacity_percent=self._config.floating.opacity_percent,
                suggestion_count=self._config.floating.suggestion_count,
            )
        if hasattr(floating, "suggestion_copied"):
            floating.suggestion_copied.connect(self._on_suggestion_copied)
        if hasattr(floating, "user_hidden_changed"):
            floating.user_hidden_changed.connect(self._on_floating_user_hidden_changed)
        if hasattr(floating, "calibration_requested"):
            floating.calibration_requested.connect(self._open_calibration_dialog)
        self._sync_floating_content()

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(168)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(6)

        brand = QLabel("WhoChat")
        brand.setObjectName("BrandMark")
        sub = QLabel("本地 AI 回复助手")
        sub.setObjectName("BrandSub")
        layout.addWidget(brand)
        layout.addWidget(sub)
        layout.addSpacing(8)

        for item in NAV_ITEMS:
            button = QPushButton(item.title)
            button.setObjectName("NavButton")
            button.setToolTip(item.subtitle)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setProperty("active", False)
            button.clicked.connect(lambda checked=False, key=item.key: self._select_page(key))
            self._nav_buttons[item.key] = button
            layout.addWidget(button)

        layout.addStretch(1)

        status = QLabel("本地优先")
        status.setObjectName("BrandSub")
        layout.addWidget(status)
        return sidebar

    def _build_content(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_topbar())
        layout.addWidget(self._pages, 1)
        return content

    def _build_topbar(self) -> QWidget:
        top = QFrame()
        top.setObjectName("TopBar")
        top.setFixedHeight(50)
        layout = QHBoxLayout(top)
        layout.setContentsMargins(18, 8, 18, 8)

        title_box = QVBoxLayout()
        self.title_label = QLabel("总览")
        self.title_label.setObjectName("PageTitle")
        self.subtitle_label = QLabel("当前仍是原型骨架，用于验证窗口、设置和交互设计。")
        self.subtitle_label.setObjectName("Muted")
        self.subtitle_label.setVisible(False)
        title_box.addWidget(self.title_label)
        title_box.addWidget(self.subtitle_label)
        layout.addLayout(title_box, 1)

        self.pause_button = QPushButton("暂停采集")
        self.pause_button.setObjectName("DangerButton")
        self.pause_button.clicked.connect(self._toggle_capture_pause)
        self.float_button = QPushButton("显示悬浮窗")
        self.float_button.setObjectName("PrimaryButton")
        self.float_button.clicked.connect(self._toggle_floating)
        layout.addWidget(self.pause_button)
        layout.addWidget(self.float_button)
        return top

    def _register_pages(self) -> None:
        pages = {
            "overview": ("总览", "当前会话、建议、风险状态和快速操作。", self._build_overview_page()),
            "contacts": ("聊天对象", "私聊、群聊、身份别名和聊天记录。", self._build_contacts_page()),
            "strategies": ("分组", "目标、语气、禁忌和手动保护。", self._build_strategies_page()),
            "memories": ("记忆", "长期记忆、临时事项和待确认内容。", self._build_memories_page()),
            "settings": ("设置", "AI Provider、隐私、采集和验证。", self._build_settings_page()),
            "diagnostics": ("诊断", "窗口识别、OCR、AI 请求和队列状态。", self._build_diagnostics_page()),
        }
        for key, (title, subtitle, page) in pages.items():
            self._page_titles[key] = title
            page.setProperty("subtitle", subtitle)
            self._pages.addWidget(page)

    def _select_page(self, key: str) -> None:
        keys = [item.key for item in NAV_ITEMS]
        index = keys.index(key)
        self._pages.setCurrentIndex(index)
        self.title_label.setText(self._page_titles[key])
        self.subtitle_label.setText(self._pages.currentWidget().property("subtitle"))
        for nav_key, button in self._nav_buttons.items():
            button.setProperty("active", nav_key == key)
            button.style().unpolish(button)
            button.style().polish(button)

    def _toggle_floating(self) -> None:
        if not self._floating:
            return
        if self._floating.isVisible():
            if hasattr(self._floating, "hide_by_user"):
                self._floating.hide_by_user()
            else:
                self._floating.hide()
            self.float_button.setText("显示悬浮窗")
            self.floating_visibility_changed.emit(False)
            return
        if hasattr(self._floating, "show_by_user"):
            self._floating.show_by_user()
        else:
            self._floating.show()
        self.float_button.setText("隐藏悬浮窗")
        self.floating_visibility_changed.emit(True)

    def _toggle_capture_pause(self) -> None:
        state = self._services.runtime.set_paused(not self._services.runtime.state.paused)
        self.append_log(f"capture_pause_changed: paused={state.paused}")

    def _on_floating_user_hidden_changed(self, hidden: bool) -> None:
        self.float_button.setText("显示悬浮窗" if hidden else "隐藏悬浮窗")

    def _on_suggestion_copied(self, text: str) -> None:
        self.statusBar().showMessage(f"已复制建议：{text[:24]}", 3000)

    def _on_pipeline_title_ready(self, _result) -> None:
        ingestion = self._services.ingestion.last_result
        if ingestion is None:
            self.append_log("pipeline_title_ready: no title ingestion result", "warning")
            return
        self.append_log(
            f"pipeline_title_ingested: accepted={ingestion.accepted}, reason={ingestion.reason}, "
            f"contact={ingestion.contact.display_name if ingestion.contact else '-'}"
        )
        if ingestion.contact:
            self._reload_contact_list(select_contact_id=ingestion.contact.id)
            self._render_contact_detail(ingestion.contact)
        self._refresh_overview_data()
        if self._runtime_text is not None:
            self._runtime_text.setText(self._format_runtime_state(self._services.runtime.state))

    def _on_pipeline_result_ready(self, _result) -> None:
        ingestion = self._services.ingestion.last_result
        if ingestion is None:
            self.append_log("pipeline_result_ready: no ingestion result", "warning")
            return
        self.append_log(
            f"pipeline_ingested: accepted={ingestion.accepted}, reason={ingestion.reason}, "
            f"inserted={ingestion.inserted_messages}, duplicate={ingestion.duplicate_messages}"
        )
        self._reload_contact_list(select_contact_id=ingestion.contact.id if ingestion.contact else None)
        if ingestion.contact:
            self._render_contact_detail(ingestion.contact)
        self._refresh_overview_data()
        if self._runtime_text is not None:
            self._runtime_text.setText(self._format_runtime_state(self._services.runtime.state))

    def _build_page_shell(self, left: QWidget, right: QWidget | None = None) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addWidget(left, 1)
        if right is not None:
            right.setFixedWidth(280)
            layout.addWidget(right)
        return page

    def _panel(self, title: str, subtitle: str | None = None) -> QFrame:
        panel = QFrame()
        panel.setObjectName("PagePanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(7)
        header = QLabel(title)
        header.setObjectName("SectionTitle")
        if subtitle:
            header.setToolTip(subtitle)
        layout.addWidget(header)
        return panel

    def _build_overview_page(self) -> QWidget:
        left = QWidget()
        layout = QVBoxLayout(left)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        metrics = QHBoxLayout()
        page_card, self._page_status_value, self._page_status_subtitle = self._metric_card_with_labels("当前页面", "unknown", "等待目标窗口")
        metrics.addWidget(page_card)
        ai_value = "未配置" if not self._config.ai.api_key and self._config.ai.provider != "Local Model" else self._config.ai.model
        ai_card, self._ai_status_value = self._metric_card_with_value("AI 状态", ai_value, self._config.ai.provider)
        metrics.addWidget(ai_card)
        capture_card, self._capture_status_value, self._capture_status_subtitle = self._metric_card_with_labels("截图门控", "暂停", "等待运行态")
        metrics.addWidget(capture_card)
        layout.addLayout(metrics)

        status_chain = self._panel("运行链路", "逐项解释当前窗口、页面、聊天对象、采集、隐私和 AI 是否满足生成条件。")
        action_banner = QFrame()
        action_banner.setObjectName("ActionBanner")
        action_layout = QHBoxLayout(action_banner)
        action_layout.setContentsMargins(10, 8, 10, 8)
        action_layout.setSpacing(10)
        next_action = QLabel("下一步：等待运行态")
        next_action.setObjectName("ActionPrimary")
        next_action.setWordWrap(False)
        next_action_meta = QLabel("未连接目标窗口")
        next_action_meta.setObjectName("TinyMuted")
        next_action_meta.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._overview_next_action = next_action
        self._overview_next_action_meta = next_action_meta
        action_layout.addWidget(next_action, 1)
        action_layout.addWidget(next_action_meta)
        status_chain.layout().addWidget(action_banner)
        status_summary = QLabel("等待运行态")
        status_summary.setObjectName("Muted")
        status_summary.setWordWrap(True)
        status_summary.setMaximumHeight(22)
        status_summary.setVisible(False)
        self._overview_status_summary = status_summary
        status_chain.layout().addWidget(status_summary)
        status_table = QTableWidget(0, 3)
        status_table.setHorizontalHeaderLabels(["环节", "状态", "原因"])
        status_table.setMinimumHeight(178)
        status_table.verticalHeader().setDefaultSectionSize(22)
        _compact_table(status_table)
        status_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        status_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        status_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        status_table.setColumnWidth(0, 86)
        status_table.setColumnWidth(1, 82)
        self._overview_status_table = status_table
        status_chain.layout().addWidget(status_table)
        layout.addWidget(status_chain)

        suggestions = self._panel("回复建议", "仅在聊天页、聊天对象与策略通过安全门控后生成；默认只复制，不自动发送。")
        self._suggestions_panel = suggestions
        self._render_reply_suggestions(self._build_reply_result())
        layout.addWidget(suggestions)

        current_chat = self._panel("当前可见聊天", "用于核对 OCR 是否把消息归属、顺序和文本识别正确。")
        table = QTableWidget(0, 5)
        table.setHorizontalHeaderLabels(["归属", "内容", "置信度", "时间来源", "状态"])
        _compact_table(table)
        self._overview_chat_table = table
        current_chat.layout().addWidget(table)
        layout.addWidget(current_chat, 1)

        right = self._build_context_rail()
        self._refresh_overview_data()
        return self._build_page_shell(left, right)

    def _metric_card(self, title: str, value: str, subtitle: str) -> QWidget:
        card, _value_label = self._metric_card_with_value(title, value, subtitle)
        return card

    def _metric_card_with_value(self, title: str, value: str, subtitle: str) -> tuple[QWidget, QLabel]:
        card, value_label, _subtitle_label = self._metric_card_with_labels(title, value, subtitle)
        return card, value_label

    def _metric_card_with_labels(self, title: str, value: str, subtitle: str) -> tuple[QWidget, QLabel, QLabel]:
        card = QFrame()
        card.setObjectName("MetricCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 10, 14, 10)
        card.setFixedHeight(72)
        card.setToolTip(subtitle)
        label = QLabel(title)
        label.setObjectName("TinyMuted")
        val = QLabel(value)
        val.setObjectName("MetricValue")
        sub = QLabel(subtitle)
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        sub.setVisible(False)
        layout.addWidget(label)
        layout.addWidget(val)
        layout.addWidget(sub)
        return card, val, sub

    def _current_contact(self) -> Contact | None:
        selected = self._selected_contact()
        if selected is not None:
            return selected
        recent = self._services.contacts.list_recent(1)
        return recent[0] if recent else None

    def _refresh_overview_data(self) -> None:
        contact = self._current_contact()
        strategy = self._services.strategies.get(contact.strategy_id) if contact else self._services.strategies.get("default")
        if self._overview_status_table is not None:
            steps = build_status_chain(
                runtime=self._services.runtime.state,
                contact=contact,
                strategy=strategy,
                config=self._config,
                reply_running=self._services.reply_tasks.is_running,
                provider_health=self._services.reply_generator.provider_health_summary(),
            )
            if self._overview_status_summary is not None:
                self._overview_status_summary.setText(" -> ".join(f"{step.stage}:{step.state}" for step in steps))
            if self._overview_next_action is not None and self._overview_next_action_meta is not None:
                primary = _primary_status_step(steps)
                self._overview_next_action.setText(f"下一步：{primary.action or primary.reason}")
                self._overview_next_action.setToolTip(_status_reason_with_action(primary))
                self._overview_next_action_meta.setText(f"{primary.stage} · {primary.state}")
                self._overview_next_action_meta.setToolTip(primary.reason)
            self._fill_table(self._overview_status_table, [(step.stage, step.state, _status_reason_with_action(step)) for step in steps])
            for row in range(self._overview_status_table.rowCount()):
                self._overview_status_table.setRowHeight(row, 22)
            self._overview_status_table.setColumnWidth(0, 86)
            self._overview_status_table.setColumnWidth(1, 82)
        if self._overview_chat_table is not None:
            rows = self._overview_chat_rows(contact)
            self._fill_table(self._overview_chat_table, rows)
        if not self._overview_contact_values and self._overview_contact_notes is None:
            return
        if contact is None:
            values = {
                "name": "未识别",
                "strategy": "默认",
                "status": "unknown",
                "cloud": "未允许",
            }
            notes = "暂无画像"
        else:
            strategy = self._services.strategies.get(contact.strategy_id)
            aliases = self._services.contacts.list_aliases(contact.id)
            memories = self._services.memories.list_for_contact(contact.id)
            values = {
                "name": _contact_display_label(contact),
                "strategy": strategy.name if strategy else contact.strategy_id,
                "status": contact.status.value,
                "cloud": "允许" if contact.allow_cloud_ai else "未允许",
            }
            alias_text = "、".join(alias.alias for alias in aliases[:8]) or "暂无"
            memory_lines = "\n".join(f"- [{memory.status.value}/{memory.kind.value}] {memory.content}" for memory in memories[:8])
            notes = f"备注：{contact.remark or '暂无'}\n别名：{alias_text}\n{memory_lines or '暂无记忆'}"
        for key, value in values.items():
            label = self._overview_contact_values.get(key)
            if label is not None:
                label.setText(value)
        if self._overview_contact_notes is not None:
            self._overview_contact_notes.setText(notes)
        self._sync_floating_content(contact=contact, strategy=strategy)

    def _sync_floating_content(self, contact: Contact | None = None, strategy: Strategy | None = None) -> None:
        if self._floating is None:
            return
        contact = contact if contact is not None else self._current_contact()
        strategy = strategy if strategy is not None else (self._services.strategies.get(contact.strategy_id) if contact else self._services.strategies.get("default"))
        if hasattr(self._floating, "update_context"):
            steps = build_status_chain(
                runtime=self._services.runtime.state,
                contact=contact,
                strategy=strategy,
                config=self._config,
                reply_running=self._services.reply_tasks.is_running,
                provider_health=self._services.reply_generator.provider_health_summary(),
            )
            ai_step = next((step for step in steps if step.stage == "AI"), steps[-1])
            ocr_step = next((step for step in steps if step.stage == "OCR"), None)
            display_step = ocr_step if ocr_step is not None and ocr_step.state in {"运行中", "读取消息"} else ai_step
            contact_name = contact.display_name if contact else (self._services.runtime.state.window.title or "未确认联系人")
            group_name = strategy.name if strategy else "默认分组"
            self._floating.update_context(
                contact_name=contact_name,
                group_name=group_name,
                status=f"{display_step.stage}:{display_step.state}",
                action=display_step.action or display_step.reason,
                app_label=self._services.runtime.state.window.app_label,
            )
            if display_step.stage == "OCR":
                if hasattr(self._floating, "disable_suggestions"):
                    self._floating.disable_suggestions()
                return
            if ai_step.state not in {"就绪", "运行中"}:
                self._floating.update_reply_result(
                    ReplyGenerationResult(False, f"blocked:{ai_step.reason}", [], self._config.ai.provider)
                )
                return
        if self._suggestion_result is not None and hasattr(self._floating, "update_reply_result"):
            self._floating.update_reply_result(self._suggestion_result)

    def _overview_chat_rows(self, contact: Contact | None) -> list[tuple[str, ...]]:
        if contact is None:
            state = self._services.runtime.state
            return [("系统", f"{state.status_label}：{state.page.reason}", "-", "runtime", "等待")]
        messages = list(reversed(self._services.messages.list_for_contact(contact.id, 12)))
        if not messages:
            return [("系统", "当前聊天对象暂无已入库聊天记录。运行采集管线或等待自动采集后会显示。", "-", "local", "空")]
        speaker_map = {
            "me": "我",
            "other": "对方",
            "member": "群成员",
            "system": "系统",
            "unknown": "未知",
        }
        return [
            (
                speaker_map.get(message.speaker.value, message.speaker.value),
                message.text,
                "-" if message.ocr_confidence is None else f"{message.ocr_confidence:.2f}",
                message.time_source,
                "截断" if message.partial else message.source,
            )
            for message in messages
        ]

    def _build_reply_context(self) -> ReplyContext:
        contact = self._current_contact()
        strategy = self._services.strategies.get(contact.strategy_id) if contact else self._services.strategies.get("default")
        messages = self._services.messages.list_for_contact(contact.id, 30) if contact else []
        memories = self._services.memories.list_for_contact(contact.id) if contact else []
        return ReplyContext(
            runtime=self._services.runtime.state,
            contact=contact,
            strategy=strategy,
            messages=messages,
            memories=memories,
        )

    def _build_reply_result(self) -> ReplyGenerationResult:
        return self._services.reply_generator.generate(self._build_reply_context(), self._config)

    def _render_reply_suggestions(self, result: ReplyGenerationResult) -> None:
        self._suggestion_result = result
        self._sync_floating_content()
        if self._suggestions_panel is None:
            return
        layout = self._suggestions_panel.layout()
        while layout.count() > 1:
            item = layout.takeAt(1)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            nested = item.layout()
            if nested is not None:
                while nested.count():
                    nested_item = nested.takeAt(0)
                    nested_widget = nested_item.widget()
                    if nested_widget is not None:
                        nested_widget.deleteLater()
        status = QLabel(f"状态：{result.status} · Provider：{result.provider}")
        status.setObjectName("TinyMuted")
        status.setMaximumHeight(18)
        status.setToolTip(result.status)
        context = self._build_reply_context()
        evidence = QLabel(_reply_evidence_summary(context, result))
        evidence.setObjectName("TinyMuted")
        evidence.setMaximumHeight(18)
        evidence.setToolTip(_reply_evidence_detail(context, result))
        actions = QHBoxLayout()
        actions.addWidget(status, 1)
        refresh = QPushButton("生成建议")
        refresh.setObjectName("PrimaryButton")
        refresh.clicked.connect(self._refresh_reply_suggestions)
        actions.addWidget(refresh)
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addWidget(evidence)
        if result.status.startswith("reply_pending"):
            pending = QLabel("生成中")
            pending.setObjectName("Muted")
            layout.addWidget(pending)
            return
        if not result.allowed:
            blocked = QLabel(f"已阻断：{result.status}")
            blocked.setObjectName("Muted")
            blocked.setToolTip("确认聊天页、聊天对象、分组策略和 AI 设置后再生成。")
            layout.addWidget(blocked)
            return
        for suggestion in result.suggestions:
            layout.addWidget(self._suggestion_row(suggestion))

    def _refresh_reply_suggestions(self) -> None:
        context = self._build_reply_context()
        if self._requires_cloud_prompt_review(context) and not self._confirm_cloud_prompt(context):
            self.statusBar().showMessage("已取消云端 AI 请求", 2500)
            self.append_log("reply_suggestions_cancelled: cloud_prompt_review")
            self._refresh_overview_data()
            return
        job_id = self._services.reply_tasks.submit(context, self._config)
        if job_id is None:
            self.statusBar().showMessage("AI 正在生成上一条建议，请稍后", 2500)
            self.append_log("reply_suggestions_skipped: busy", "warning")
            self._refresh_overview_data()
            return
        pending = ReplyGenerationResult(False, f"reply_pending: job={job_id}", [], self._config.ai.provider)
        self._render_reply_suggestions(pending)
        self._refresh_overview_data()
        self.statusBar().showMessage("正在生成回复建议", 2500)
        self.append_log(f"reply_suggestions_submitted: job={job_id}")

    def _on_reply_task_ready(self, task: ReplyTaskResult) -> None:
        current = self._build_reply_context()
        current_contact_id = current.contact.id if current.contact else None
        if task.contact_id != current_contact_id or task.hwnd != current.runtime.window.hwnd:
            self.append_log(
                (
                    "reply_suggestions_stale: "
                    f"job={task.job_id}, task_contact={task.contact_id or '-'}, "
                    f"current_contact={current_contact_id or '-'}, task_hwnd={task.hwnd or '-'}, "
                    f"current_hwnd={current.runtime.window.hwnd or '-'}"
                ),
                "warning",
            )
            self._render_reply_suggestions(
                ReplyGenerationResult(False, "blocked:reply_context_changed", [], self._config.ai.provider)
            )
            self.statusBar().showMessage("聊天对象已变化，已丢弃旧建议", 2500)
            self._refresh_overview_data()
            return
        self._render_reply_suggestions(task.result)
        self.append_log(f"reply_suggestions_ready: job={task.job_id}, allowed={task.result.allowed}, status={task.result.status}")
        self.statusBar().showMessage("回复建议已更新", 2500)
        self._refresh_generation_log_text()
        self._refresh_overview_data()
        if self._runtime_text is not None:
            self._runtime_text.setText(self._format_runtime_state(self._services.runtime.state))

    def _on_reply_task_discarded(self, reason: str) -> None:
        self.append_log(f"reply_task_discarded: {reason}", "warning")
        self._refresh_overview_data()
        if self._runtime_text is not None:
            self._runtime_text.setText(self._format_runtime_state(self._services.runtime.state))

    def _on_reply_task_status_changed(self, status: str) -> None:
        self.append_log(f"reply_task_status: {status}")
        self._refresh_overview_data()
        if self._runtime_text is not None:
            self._runtime_text.setText(self._format_runtime_state(self._services.runtime.state))

    def _requires_cloud_prompt_review(self, context: ReplyContext) -> bool:
        return (
            self._config.privacy.require_cloud_prompt_review
            and self._config.ai.provider in {"OpenAI", "OpenAI Compatible"}
            and bool(self._config.ai.api_key)
            and context.contact is not None
            and context.contact.allow_cloud_ai
        )

    def _confirm_cloud_prompt(self, context: ReplyContext) -> bool:
        preview = build_prompt_preview(context, self._config)
        dialog = QDialog(self)
        dialog.setWindowTitle("确认云端 AI 请求")
        dialog.setMinimumSize(720, 560)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        summary = QLabel(self._format_prompt_preview_summary(preview))
        summary.setWordWrap(True)
        summary.setObjectName("Muted")
        layout.addWidget(summary)
        body = QTextEdit()
        body.setReadOnly(True)
        body.setText(preview.combined_text)
        layout.addWidget(body, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确认发送给 AI")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        return dialog.exec() == QDialog.DialogCode.Accepted

    def _format_prompt_preview_summary(self, preview: PromptPreview) -> str:
        return (
            f"Provider：{preview.provider} · 模型：{preview.model}\n"
            f"上下文：消息 {preview.message_count} 条，记忆 {preview.memory_count} 条\n"
            f"脱敏：{preview.redaction_summary}"
        )

    def _suggestion_row(self, suggestion: ReplySuggestion) -> QWidget:
        row = QFrame()
        row.setObjectName("MetricCard")
        layout = QGridLayout(row)
        layout.setContentsMargins(10, 8, 10, 8)
        tag = QLabel(suggestion.label)
        tag.setObjectName("Badge")
        tag.setMinimumWidth(58)
        tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body = QLabel(suggestion.text)
        body.setWordWrap(True)
        risk_label = QLabel(f"risk: {suggestion.risk}")
        risk_label.setObjectName("TinyMuted")
        risk_label.setToolTip(suggestion.rationale)
        risk_label.setText(f"{suggestion.risk} · {_clip_debug_text(suggestion.rationale, 72)}")
        useful = QPushButton("好用")
        useful.clicked.connect(lambda: self._record_reply_feedback(suggestion, "useful"))
        bad = QPushButton("不合适")
        bad.clicked.connect(lambda: self._record_reply_feedback(suggestion, "bad"))
        copy = QPushButton("复制")
        copy.clicked.connect(lambda: self._copy_reply_suggestion(suggestion.text))
        layout.addWidget(tag, 0, 0)
        layout.addWidget(body, 0, 1, 1, 2)
        layout.addWidget(risk_label, 1, 1)
        layout.addWidget(useful, 1, 2)
        layout.addWidget(bad, 1, 3)
        layout.addWidget(copy, 0, 4, 2, 1)
        layout.setColumnStretch(1, 1)
        return row

    def _copy_reply_suggestion(self, text: str) -> None:
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage(f"已复制建议：{text[:24]}", 3000)
        self.append_log("reply_suggestion_copied")

    def _record_reply_feedback(self, suggestion: ReplySuggestion, feedback: str) -> None:
        result = self._suggestion_result
        if result is None or not result.allowed:
            self.statusBar().showMessage("当前没有可评价的回复建议", 2500)
            return
        context = self._build_reply_context()
        digest = _reply_context_hash(context)
        record = self._services.reply_feedback.append(
            contact_id=context.contact.id if context.contact else None,
            strategy_id=context.strategy.id if context.strategy else None,
            provider=result.provider,
            status=result.status,
            suggestion_label=suggestion.label,
            suggestion_text=suggestion.text,
            risk=suggestion.risk,
            feedback=feedback,
            context_hash=digest,
            page_type=context.runtime.page.page_type.value,
            message_count=len(context.messages),
            memory_count=len(context.memories),
        )
        label = "好用" if feedback == "useful" else "不合适"
        self.statusBar().showMessage(f"已记录反馈：{label}", 2500)
        self.append_log(f"reply_feedback_recorded: {record.id} feedback={feedback}")
        if context.contact is not None:
            self._render_contact_detail(context.contact)
        self._refresh_generation_log_text()

    def _build_context_rail(self) -> QWidget:
        rail = QFrame()
        rail.setObjectName("RightRail")
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        title = QLabel("当前聊天对象画像")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        self._overview_contact_values = {}
        for label, value, key in [
            ("聊天对象", "未识别", "name"),
            ("分组", "默认", "strategy"),
            ("确认等级", "unknown", "status"),
            ("云端 AI", "未允许", "cloud"),
        ]:
            row, value_label = self._kv(label, value)
            self._overview_contact_values[key] = value_label
            layout.addWidget(row)

        notes = QTextEdit()
        notes.setReadOnly(True)
        notes.setText("暂无画像")
        notes.setMinimumHeight(72)
        notes.setMaximumHeight(104)
        self._overview_contact_notes = notes
        layout.addWidget(notes)

        layout.addWidget(QLabel("操作", objectName="SectionTitle"))
        confirm = QPushButton("确认当前对象")
        confirm.clicked.connect(lambda: self._update_selected_contact_status(ContactStatus.CONFIRMED))
        merge = QPushButton("合并对象")
        merge.clicked.connect(self._merge_selected_contact)
        protect = QPushButton("进入手动回复保护")
        protect.clicked.connect(self._protect_selected_contact)
        action_grid = QGridLayout()
        action_grid.setSpacing(6)
        action_grid.addWidget(confirm, 0, 0)
        action_grid.addWidget(merge, 0, 1)
        action_grid.addWidget(protect, 1, 0, 1, 2)
        layout.addLayout(action_grid)
        layout.addStretch(1)
        return rail

    def _kv(self, key: str, value: str) -> tuple[QWidget, QLabel]:
        box = QWidget()
        layout = QHBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        k = QLabel(key)
        k.setObjectName("Muted")
        v = QLabel(value)
        v.setObjectName("Badge")
        layout.addWidget(k)
        layout.addStretch(1)
        layout.addWidget(v)
        return box, v

    def _build_contacts_page(self) -> QWidget:
        splitter = QWidget()
        layout = QHBoxLayout(splitter)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        list_panel = self._panel("聊天对象", "私聊和群聊都可以查看画像、别名、分组和聊天记录。")
        contact_list = QListWidget()
        self._contact_list = contact_list
        contacts = self._reload_contact_list()
        list_panel.layout().addWidget(contact_list)
        layout.addWidget(list_panel, 1)

        detail = self._panel("对象详情", "此处展示选中私聊或群聊的画像、身份线索和聊天摘要。")
        tabs = QTabWidget()
        self._contact_profile_text = self._readonly_text("画像", "暂无聊天对象。需要先从当前会话识别或手动创建。")
        self._contact_identity_text = self._readonly_text("身份", "暂无身份链接。")
        self._contact_members_text = self._readonly_text("群成员", "仅群聊可用。")
        self._contact_chat_text = self._readonly_text("聊天记录", "暂无聊天记录。")
        self._contact_memory_text = self._readonly_text("记忆", "暂无记忆。")
        self._contact_feedback_text = self._readonly_text("回复反馈", "暂无回复反馈。")
        tabs.addTab(self._contact_profile_text, "画像")
        tabs.addTab(self._contact_identity_text, "身份")
        tabs.addTab(self._contact_members_text, "群成员")
        tabs.addTab(self._contact_chat_text, "聊天记录")
        tabs.addTab(self._contact_memory_text, "记忆")
        tabs.addTab(self._contact_feedback_text, "回复反馈")
        detail.layout().addWidget(tabs)
        actions = QGridLayout()
        actions.setSpacing(6)
        confirm = QPushButton("确认")
        confirm.clicked.connect(lambda: self._update_selected_contact_status(ContactStatus.CONFIRMED))
        edit = QPushButton("编辑")
        edit.clicked.connect(self._edit_selected_contact_profile)
        alias = QPushButton("别名")
        alias.clicked.connect(self._add_alias_to_selected_contact)
        merge = QPushButton("合并")
        merge.clicked.connect(self._merge_selected_contact)
        link_identity = QPushButton("链接身份")
        link_identity.clicked.connect(self._link_selected_contact_identity)
        new_identity = QPushButton("新建身份")
        new_identity.clicked.connect(self._create_identity_for_selected_contact)
        person_alias = QPushButton("身份别名")
        person_alias.clicked.connect(self._add_alias_to_selected_person)
        add_member = QPushButton("添加成员")
        add_member.clicked.connect(self._add_member_to_selected_group)
        member_identity = QPushButton("成员身份")
        member_identity.clicked.connect(self._link_selected_group_member_identity)
        member_contact = QPushButton("成员对象")
        member_contact.clicked.connect(self._link_selected_group_member_contact)
        protect = QPushButton("保护")
        protect.clicked.connect(self._protect_selected_contact)
        export = QPushButton("导出")
        export.clicked.connect(self._export_selected_contact_data)
        clear = QPushButton("清空")
        clear.clicked.connect(self._clear_selected_contact_data)
        buttons = [
            confirm,
            edit,
            alias,
            merge,
            link_identity,
            new_identity,
            person_alias,
            add_member,
            member_identity,
            member_contact,
            protect,
            export,
            clear,
        ]
        for index, button in enumerate(buttons):
            actions.addWidget(button, index // 7, index % 7)
        detail.layout().addLayout(actions)
        layout.addWidget(detail, 2)
        contact_list.currentItemChanged.connect(self._on_contact_selected)
        if contacts:
            contact_list.setCurrentRow(0)
        return self._build_page_shell(splitter)

    def _reload_contact_list(self, select_contact_id: str | None = None) -> list[Contact]:
        if self._contact_list is None:
            return []
        self._contact_list.blockSignals(True)
        self._contact_list.clear()
        contacts = self._services.contacts.list_recent()
        selected_row = -1
        if contacts:
            for index, contact in enumerate(contacts):
                item = QListWidgetItem(f"{_contact_display_label(contact)} · {contact.status.value} · {contact.conversation_type.value}")
                item.setData(Qt.ItemDataRole.UserRole, contact.id)
                item.setToolTip(f"{contact.platform} · {contact.display_name}")
                self._contact_list.addItem(item)
                if contact.id == select_contact_id:
                    selected_row = index
        else:
            QListWidgetItem("暂无聊天对象\n打开私聊或群聊并确认后会显示在这里", self._contact_list)
        self._contact_list.blockSignals(False)
        if selected_row >= 0:
            self._contact_list.setCurrentRow(selected_row)
        return contacts

    def _build_strategies_page(self) -> QWidget:
        page = self._panel("分组策略", "预设只是模板，用户可以为每个分组定义自己的目标、语气和禁忌。")
        filters = QHBoxLayout()
        search = QLineEdit()
        search.setPlaceholderText("搜索分组、目标、语气或禁忌")
        search.textChanged.connect(lambda _value: self._reload_strategy_table())
        show_archived = QCheckBox("显示归档")
        show_archived.stateChanged.connect(lambda _value: self._reload_strategy_table())
        self._strategy_search = search
        self._strategy_show_archived = show_archived
        filters.addWidget(search, 1)
        filters.addWidget(show_archived)
        page.layout().addLayout(filters)

        table = QTableWidget(0, 6)
        self._strategy_table = table
        table.setHorizontalHeaderLabels(["分组", "目标", "语气", "保护", "状态", "使用"])
        _compact_table(table)
        table.itemDoubleClicked.connect(lambda _item: self._edit_selected_strategy())
        page.layout().addWidget(table)
        actions = QHBoxLayout()
        add = QPushButton("新增分组")
        add.clicked.connect(self._add_strategy)
        duplicate = QPushButton("复制为新策略")
        duplicate.clicked.connect(self._duplicate_selected_strategy)
        edit = QPushButton("编辑目标")
        edit.clicked.connect(self._edit_selected_strategy)
        archive = QPushButton("归档/恢复")
        archive.clicked.connect(self._toggle_selected_strategy_archive)
        actions.addWidget(add)
        actions.addWidget(duplicate)
        actions.addWidget(edit)
        actions.addWidget(archive)
        actions.addStretch(1)
        page.layout().addLayout(actions)
        self._reload_strategy_table()
        return self._build_page_shell(page)

    def _build_memories_page(self) -> QWidget:
        page = self._panel("记忆整理", "AI 提取的新记忆会先进入待确认区，避免 OCR 错误污染长期画像。")
        tabs = QTabWidget()
        self._memory_tabs = tabs
        tabs.addTab(self._build_memory_review_tab(MemoryStatus.PENDING), "待确认")
        tabs.addTab(self._build_memory_review_tab(MemoryStatus.CONFIRMED), "长期画像")
        tabs.addTab(self._build_memory_review_tab(MemoryStatus.REJECTED), "已拒绝")
        page.layout().addWidget(tabs)
        return self._build_page_shell(page)

    def _build_settings_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        ai = self._panel("自定义 AI", "支持 OpenAI 和第三方 GPT 兼容接口。API Key 只用于本地配置，不应写入日志。")
        form = QGridLayout()
        provider = QComboBox()
        provider.addItems(["OpenAI Compatible", "OpenAI", "Local Model", "Disabled"])
        provider.setCurrentText(self._config.ai.provider)
        base_url = QLineEdit(self._config.ai.base_url)
        model = QLineEdit(self._config.ai.model)
        api_key = QLineEdit()
        api_key.setText(self._config.ai.api_key)
        api_key.setEchoMode(QLineEdit.EchoMode.Password)
        temperature = QDoubleSpinBox()
        temperature.setRange(0.0, 2.0)
        temperature.setSingleStep(0.1)
        temperature.setValue(self._config.ai.temperature)
        max_context = QSpinBox()
        max_context.setRange(1000, 200000)
        max_context.setValue(self._config.ai.context_tokens)
        timeout = QSpinBox()
        timeout.setRange(5, 300)
        timeout.setValue(self._config.ai.timeout_seconds)
        cooldown = QSpinBox()
        cooldown.setRange(0, 300)
        cooldown.setValue(self._config.ai.request_cooldown_seconds)
        dedupe = QSpinBox()
        dedupe.setRange(0, 1440)
        dedupe.setValue(self._config.ai.dedupe_context_minutes)
        daily_limit = QSpinBox()
        daily_limit.setRange(0, 10000)
        daily_limit.setValue(self._config.ai.max_daily_cloud_requests)
        failure_threshold = QSpinBox()
        failure_threshold.setRange(1, 20)
        failure_threshold.setValue(self._config.ai.failure_backoff_threshold)
        failure_backoff = QSpinBox()
        failure_backoff.setRange(0, 240)
        failure_backoff.setValue(self._config.ai.failure_backoff_minutes)
        health_label = QLabel(self._services.reply_generator.provider_health_summary())
        health_label.setObjectName("TinyMuted")
        self._ai_health_label = health_label
        self._ai_provider = provider
        self._ai_base_url = base_url
        self._ai_model = model
        self._ai_api_key = api_key
        self._ai_temperature = temperature
        self._ai_context_tokens = max_context
        self._ai_timeout = timeout
        self._ai_request_cooldown = cooldown
        self._ai_dedupe_minutes = dedupe
        self._ai_daily_limit = daily_limit
        self._ai_failure_threshold = failure_threshold
        self._ai_failure_backoff = failure_backoff
        for row, (label, widget) in enumerate([
            ("服务类型", provider),
            ("接口地址", base_url),
            ("模型名称", model),
            ("API Key", api_key),
            ("温度", temperature),
            ("上下文上限", max_context),
            ("超时时间（秒）", timeout),
            ("云端冷却（秒）", cooldown),
            ("重复上下文（分钟）", dedupe),
            ("每日云端上限", daily_limit),
            ("失败退避阈值", failure_threshold),
            ("失败退避（分钟）", failure_backoff),
            ("健康状态", health_label),
        ]):
            form.addWidget(QLabel(label), row, 0)
            form.addWidget(widget, row, 1)
        ai.layout().addLayout(form)
        ai_actions = QHBoxLayout()
        test_ai = QPushButton("测试连接")
        test_ai.clicked.connect(self._test_ai_settings)
        ai_actions.addWidget(test_ai)
        reset_health = QPushButton("恢复健康状态")
        reset_health.clicked.connect(self._reset_ai_provider_health)
        ai_actions.addWidget(reset_health)
        save_ai = QPushButton("保存设置")
        save_ai.setObjectName("PrimaryButton")
        save_ai.clicked.connect(self._save_ai_settings)
        ai_actions.addWidget(save_ai)
        ai_actions.addStretch(1)
        ai.layout().addLayout(ai_actions)
        layout.addWidget(ai)

        privacy = self._panel("隐私与数据", "默认本地保存，用户可以关闭截图保存和长期记忆。")
        privacy_items = [
            ("启用长期记忆", self._config.privacy.enable_long_term_memory, "_privacy_long_memory"),
            ("保存截图样本用于调试", self._config.privacy.save_debug_screenshots, "_privacy_debug_screenshots"),
            ("云端请求前裁剪上下文", self._config.privacy.trim_context_for_cloud, "_privacy_trim_cloud"),
            ("云端请求前预览并确认", self._config.privacy.require_cloud_prompt_review, "_privacy_cloud_review"),
            ("手动回复保护默认不生成可复制回复", self._config.privacy.manual_protection_blocks_replies, "_privacy_manual_blocks"),
        ]
        for text, checked, attr in privacy_items:
            checkbox = QCheckBox(text)
            checkbox.setChecked(checked)
            setattr(self, attr, checkbox)
            privacy.layout().addWidget(checkbox)
        retention_form = QGridLayout()
        self._privacy_log_retention = _days_spin(self._config.privacy.diagnostic_log_retention_days)
        self._privacy_debug_retention = _days_spin(self._config.privacy.debug_sample_retention_days)
        self._privacy_capture_retention = _days_spin(self._config.privacy.capture_retention_days)
        self._privacy_calibration_retention = _days_spin(self._config.privacy.calibration_retention_days)
        self._privacy_feedback_retention = _days_spin(self._config.privacy.reply_feedback_retention_days)
        for row, (label, widget) in enumerate([
            ("日志保留", self._privacy_log_retention),
            ("调试样本", self._privacy_debug_retention),
            ("截图缓存", self._privacy_capture_retention),
            ("校准样本", self._privacy_calibration_retention),
            ("回复反馈", self._privacy_feedback_retention),
        ]):
            retention_form.addWidget(QLabel(label), row // 2, (row % 2) * 2)
            retention_form.addWidget(widget, row // 2, (row % 2) * 2 + 1)
        privacy.layout().addLayout(retention_form)
        governance_actions = QHBoxLayout()
        export_all = QPushButton("全局导出")
        export_all.clicked.connect(self._export_all_data)
        cleanup_local = QPushButton("立即清理")
        cleanup_local.clicked.connect(self._run_retention_cleanup)
        clear_all = QPushButton("清空全部内容")
        clear_all.setObjectName("DangerButton")
        clear_all.clicked.connect(self._clear_all_content)
        governance_actions.addWidget(export_all)
        governance_actions.addWidget(cleanup_local)
        governance_actions.addWidget(clear_all)
        governance_actions.addStretch(1)
        privacy.layout().addLayout(governance_actions)
        layout.addWidget(privacy)

        ocr = self._panel("OCR 识别", "默认预览引擎只用于验证坐标流；真实本地识别可选择 RapidOCR 或 PaddleOCR。")
        ocr_form = QGridLayout()
        ocr_provider = QComboBox()
        ocr_provider.addItems(["Preview Fixture", "RapidOCR", "PaddleOCR"])
        ocr_provider.setCurrentText(self._config.ocr.provider)
        ocr_language = QLineEdit(self._config.ocr.language)
        ocr_min_confidence = QDoubleSpinBox()
        ocr_min_confidence.setRange(0.0, 1.0)
        ocr_min_confidence.setSingleStep(0.05)
        ocr_min_confidence.setValue(self._config.ocr.min_confidence)
        ocr_use_gpu = QCheckBox("启用 GPU（取决于 OCR 库和本机环境）")
        ocr_use_gpu.setChecked(self._config.ocr.use_gpu)
        self._ocr_provider = ocr_provider
        self._ocr_language = ocr_language
        self._ocr_min_confidence = ocr_min_confidence
        self._ocr_use_gpu = ocr_use_gpu
        for row, (label, widget) in enumerate([
            ("识别引擎", ocr_provider),
            ("语言", ocr_language),
            ("最低置信度", ocr_min_confidence),
            ("硬件", ocr_use_gpu),
        ]):
            ocr_form.addWidget(QLabel(label), row, 0)
            ocr_form.addWidget(widget, row, 1)
        ocr.layout().addLayout(ocr_form)
        layout.addWidget(ocr)

        capture = self._panel("采集与防抖", "控制 OCR 和 AI 请求频率，避免滚动时产生大量请求。")
        self._capture_auto_enabled = QCheckBox("自动跟随目标窗口采集")
        self._capture_auto_enabled.setChecked(self._config.capture.auto_capture_enabled)
        capture.layout().addWidget(self._capture_auto_enabled)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(100, 3000)
        slider.setValue(self._config.capture.scroll_debounce_ms)
        self._capture_debounce = slider
        self._capture_debounce_label = QLabel(f"滚动停止防抖：{slider.value()} ms")
        slider.valueChanged.connect(lambda value: self._capture_debounce_label.setText(f"滚动停止防抖：{value} ms"))
        capture.layout().addWidget(self._capture_debounce_label)
        capture.layout().addWidget(slider)
        ocr_interval = QSpinBox()
        ocr_interval.setRange(2500, 60000)
        ocr_interval.setSingleStep(1000)
        ocr_interval.setSuffix(" ms")
        ocr_interval.setValue(self._config.capture.ocr_min_interval_ms)
        self._capture_ocr_interval = ocr_interval
        interval_row = QHBoxLayout()
        interval_row.addWidget(QLabel("自动 OCR 最小间隔"))
        interval_row.addWidget(ocr_interval)
        interval_row.addStretch(1)
        capture.layout().addLayout(interval_row)
        self._capture_pause_unknown = QCheckBox("页面类型未知时暂停 AI 请求")
        self._capture_pause_unknown.setChecked(self._config.capture.pause_ai_on_unknown_page)
        self._capture_block_unconfirmed = QCheckBox("联系人未确认时禁止写入长期画像")
        self._capture_block_unconfirmed.setChecked(self._config.capture.block_memory_for_unconfirmed_contact)
        capture.layout().addWidget(self._capture_pause_unknown)
        capture.layout().addWidget(self._capture_block_unconfirmed)
        layout.addWidget(capture)

        floating = self._panel("悬浮窗", "控制贴边位置、透明度和可见回复数量。")
        floating_form = QGridLayout()
        placement = QComboBox()
        placement.addItems(["auto", "bottom", "top", "right", "left"])
        placement.setCurrentText(self._config.floating.placement_preference)
        opacity = QSpinBox()
        opacity.setRange(70, 100)
        opacity.setSuffix("%")
        opacity.setValue(self._config.floating.opacity_percent)
        suggestion_count = QSpinBox()
        suggestion_count.setRange(1, 3)
        suggestion_count.setValue(self._config.floating.suggestion_count)
        self._floating_placement = placement
        self._floating_opacity = opacity
        self._floating_suggestion_count = suggestion_count
        for row, (label, widget) in enumerate([
            ("贴靠优先", placement),
            ("透明度", opacity),
            ("回复数量", suggestion_count),
        ]):
            floating_form.addWidget(QLabel(label), row, 0)
            floating_form.addWidget(widget, row, 1)
        floating.layout().addLayout(floating_form)
        layout.addWidget(floating)

        targets = self._panel("目标应用", None)
        target_grid = QGridLayout()
        self._target_grid = target_grid
        self._refresh_target_grid()
        target_grid.setColumnStretch(2, 1)
        target_grid.setColumnStretch(3, 1)
        target_grid.setColumnStretch(4, 1)
        targets.layout().addLayout(target_grid)
        target_actions = QHBoxLayout()
        add_target = QPushButton("新增应用")
        add_target.clicked.connect(self._add_target_app)
        target_actions.addWidget(add_target)
        target_actions.addStretch(1)
        targets.layout().addLayout(target_actions)
        layout.addWidget(targets)

        layout.addStretch(1)
        scroll.setWidget(body)
        return self._build_page_shell(scroll)

    def _build_diagnostics_page(self) -> QWidget:
        page = self._panel("诊断控制台", "日志保持简洁、精准，可用于定位窗口识别、OCR 和 AI 请求问题。")
        runtime = QTextEdit()
        runtime.setReadOnly(True)
        runtime.setMinimumHeight(112)
        self._runtime_text = runtime
        runtime.setText(self._format_runtime_state(self._services.runtime.state))
        page.layout().addWidget(runtime)

        environment = QTextEdit()
        environment.setReadOnly(True)
        environment.setMinimumHeight(86)
        environment.setMaximumHeight(130)
        self._environment_text = environment
        environment.setText(self._format_environment_checks())
        page.layout().addWidget(environment)

        window_match = QTextEdit()
        window_match.setReadOnly(True)
        window_match.setMinimumHeight(76)
        window_match.setMaximumHeight(120)
        self._window_match_text = window_match
        window_match.setText(self._format_window_match_diagnostics())
        window_match_toolbar = QHBoxLayout()
        window_match_toolbar.addWidget(QLabel("窗口诊断"))
        window_match_toolbar.addStretch(1)
        refresh_window = QPushButton("刷新窗口")
        refresh_window.clicked.connect(self._refresh_window_match_diagnostics)
        window_match_toolbar.addWidget(refresh_window)
        copy_window = QPushButton("复制窗口")
        copy_window.clicked.connect(self._copy_window_match_diagnostics)
        window_match_toolbar.addWidget(copy_window)
        page.layout().addLayout(window_match_toolbar)
        page.layout().addWidget(window_match)

        log = QTextEdit()
        log.setReadOnly(True)
        self._log_text = log
        log_toolbar = QHBoxLayout()
        level_filter = QComboBox()
        level_filter.addItems(["全部", "debug", "info", "warning", "error"])
        level_filter.currentTextChanged.connect(lambda _value: self._refresh_ui_log_text())
        self._log_level_filter = level_filter
        log_toolbar.addWidget(QLabel("日志级别"))
        log_toolbar.addWidget(level_filter)
        log_toolbar.addStretch(1)
        page.layout().addLayout(log_toolbar)
        self._refresh_ui_log_text()
        self._pending_logs.clear()
        page.layout().addWidget(log)

        diagnostics_files = QTextEdit()
        diagnostics_files.setReadOnly(True)
        diagnostics_files.setMinimumHeight(70)
        diagnostics_files.setMaximumHeight(120)
        self._diagnostics_file_text = diagnostics_files
        diagnostics_files.setText(self._format_diagnostics_files())
        page.layout().addWidget(diagnostics_files)

        generation_log = QTextEdit()
        generation_log.setReadOnly(True)
        generation_log.setMinimumHeight(78)
        self._generation_log_text = generation_log
        self._refresh_generation_log_text()
        page.layout().addWidget(generation_log)

        actions = QHBoxLayout()
        copy_logs = QPushButton("复制日志")
        copy_logs.clicked.connect(self._copy_diagnostics_bundle)
        actions.addWidget(copy_logs)
        save_sample = QPushButton("保存调试样本")
        save_sample.clicked.connect(self._save_debug_sample)
        actions.addWidget(save_sample)
        run_pipeline = QPushButton("运行采集管线")
        run_pipeline.clicked.connect(self._run_capture_pipeline)
        actions.addWidget(run_pipeline)
        recalibrate = QPushButton("重新校准区域")
        recalibrate.clicked.connect(self._open_calibration_dialog)
        actions.addWidget(recalibrate)
        actions.addStretch(1)
        page.layout().addLayout(actions)
        return self._build_page_shell(page)

    def _format_environment_checks(self) -> str:
        return self._services.environment.format_text()

    def _format_window_match_diagnostics(self) -> str:
        targets = [target for target in self._config.targets if target.enabled]
        target_line = "enabled_targets=" + ",".join(
            f"{target.app_id}:{target.label}"
            f"(process={','.join(target.process_names) or '-'};"
            f"title={','.join(target.title_keywords) or '-'};"
            f"exclude={','.join(target.exclude_title_keywords) or '-'})"
            for target in targets
        )
        candidates = diagnose_target_windows(self._config.targets, limit=12)
        foreground = foreground_window_handle()
        if not candidates:
            return "\n".join(
                [
                    target_line,
                    f"foreground_hwnd={foreground or '-'}",
                    "related_windows=0",
                    "action=未发现相关窗口。请打开已启用的聊天应用，或在设置中补充进程名/标题关键词。",
                ]
            )
        matched_foreground = next((item for item in candidates if item.foreground and item.matched), None)
        foreground_excluded = next((item for item in candidates if item.foreground and item.reason == "excluded_by_title"), None)
        matched_background = [item for item in candidates if item.matched and not item.foreground]
        lines = [
            target_line,
            f"foreground_hwnd={foreground or '-'}",
            f"related_windows={len(candidates)}",
            _window_match_action(matched_foreground, foreground_excluded, matched_background),
        ]
        for item in candidates:
            target = item.target_app or "-"
            label = item.app_label or "-"
            process = item.process_name or "-"
            lines.append(
                f"hwnd={item.hwnd} foreground={item.foreground} matched={item.matched} "
                f"process={process} target={target}/{label} reason={item.reason} title={item.title}"
            )
        return "\n".join(lines)

    def _refresh_window_match_diagnostics(self) -> None:
        if self._window_match_text is not None:
            self._window_match_text.setText(self._format_window_match_diagnostics())
        if self._runtime_text is not None:
            self._runtime_text.setText(self._format_runtime_state(self._services.runtime.state))
        self.statusBar().showMessage("窗口诊断已刷新", 2500)
        self.append_log("window_match_diagnostics_refreshed")

    def _copy_window_match_diagnostics(self) -> None:
        text = redact_diagnostics_text(self._format_window_match_diagnostics())
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage("窗口诊断已复制", 2500)
        self.append_log("window_match_diagnostics_copied")

    def _refresh_ui_log_text(self) -> None:
        if self._log_text is None:
            return
        selected = self._log_level_filter.currentText() if self._log_level_filter else "全部"
        logs = list(reversed(self._services.logs.tail(120)))
        if selected != "全部":
            logs = [item for item in logs if item.level == selected]
        text = "\n".join(_format_app_log(item) for item in logs)
        if selected == "全部" and self._pending_logs:
            text = "\n".join([text, *self._pending_logs]).strip()
        self._log_text.setText(text or f"[{selected}] 暂无")

    def _format_diagnostics_files(self) -> str:
        crash_log = diagnostics_log_path("crash")
        ocr_log = diagnostics_log_path("ocr_worker")
        ai_log = diagnostics_log_path("ai_provider")
        lines = [
            f"crash_log={crash_log}",
            f"ocr_worker_log={ocr_log}",
            f"ai_provider_log={ai_log}",
            "ocr_worker_tail:",
            *_tail_lines(ocr_log, 5),
            "ai_provider_tail:",
            *_tail_lines(ai_log, 5),
            "capture_samples:",
            *self._format_capture_performance_summary(20),
            *self._format_capture_sample_lines(5),
        ]
        return "\n".join(lines)

    def _format_capture_performance_summary(self, limit: int = 20) -> list[str]:
        samples = [
            item for item in self._services.capture_samples.tail(limit)
            if item.total_elapsed_ms is not None
        ]
        if not samples:
            return ["capture_perf=暂无"]
        title_values = [item.title_ocr_elapsed_ms for item in samples if item.title_ocr_elapsed_ms is not None]
        content_values = [item.content_ocr_elapsed_ms for item in samples if item.content_ocr_elapsed_ms is not None]
        total_values = [item.total_elapsed_ms for item in samples if item.total_elapsed_ms is not None]
        slowest = max(samples, key=lambda item: item.total_elapsed_ms or 0)
        avg_total = _avg_number(total_values)
        status, action = _capture_perf_status(avg_total)
        return [
            (
                f"capture_perf=status:{status} count:{len(samples)} "
                f"avg_title_ms:{_avg_int(title_values)} "
                f"avg_content_ms:{_avg_int(content_values)} "
                f"avg_total_ms:{_avg_int(total_values)} "
                f"slowest_job:{slowest.job_id} slowest_total_ms:{slowest.total_elapsed_ms} "
                f"action:{action}"
            )
        ]

    def _format_capture_sample_lines(self, limit: int = 5) -> list[str]:
        samples = self._services.capture_samples.tail(limit)
        if not samples:
            return ["暂无"]
        return [
            (
                f"job={item.job_id} app={item.target_app}/{item.app_label} page={item.page_type} "
                f"messages={item.message_count} title_ms={item.title_ocr_elapsed_ms if item.title_ocr_elapsed_ms is not None else '-'} "
                f"content_ms={item.content_ocr_elapsed_ms if item.content_ocr_elapsed_ms is not None else '-'} "
                f"total_ms={item.total_elapsed_ms if item.total_elapsed_ms is not None else '-'}"
            )
            for item in samples
        ]

    def _diagnostics_bundle_text(self) -> str:
        state = self._services.runtime.state
        sections = [
            "# runtime",
            self._format_runtime_state(state),
            "",
            "# ui_logs",
            "\n".join(f"[{item.level}] {item.ts} {item.module}.{item.event}: {item.message}" for item in reversed(self._services.logs.tail(80))) or "暂无",
            "",
            "# environment",
            self._format_environment_checks(),
            "",
            "# window_matching",
            self._format_window_match_diagnostics(),
            "",
            "# generation_logs",
            self._format_generation_log_lines(20),
            "",
            "# reply_feedback",
            self._format_reply_feedback_lines(20),
            "",
            "# capture_samples",
            "\n".join(self._format_capture_sample_lines(10)),
            "",
            "# files",
            self._format_diagnostics_files(),
        ]
        return "\n".join(sections)

    def _copy_diagnostics_bundle(self) -> None:
        text = redact_diagnostics_text(self._diagnostics_bundle_text())
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage("诊断日志已复制", 3000)
        self.append_log("diagnostics_bundle_copied")

    def _save_debug_sample(self) -> None:
        output_dir = app_data_dir() / "debug_samples"
        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = utc_now_iso().replace(":", "-")
        sample_dir = output_dir / f"sample-{stamp}"
        sample_dir.mkdir(parents=True, exist_ok=True)
        state = self._services.runtime.state
        last_result = self._services.pipeline.last_result
        last_title = self._services.pipeline.last_title_result
        payload = {
            "export": {
                "app": "WhoChat",
                "schema_version": 1,
                "exported_at": utc_now_iso(),
                "scope": "diagnostics",
            },
            "runtime": self._format_runtime_state(state),
            "environment": [asdict(item) for item in self._services.environment.checks()],
            "window_matching": [asdict(item) for item in diagnose_target_windows(self._config.targets, limit=20)],
            "pipeline": {
                "last_status": self._services.pipeline.last_status,
                "last_discard_reason": self._services.pipeline.last_discard_reason,
                "last_title_job_id": last_title.job_id if last_title else None,
                "last_title_target_app": last_title.target_app if last_title else None,
                "last_title_app_label": last_title.app_label if last_title else None,
                "last_title_image": str(last_title.title_ocr_image_path) if last_title else None,
                "last_title_crop_rect": last_title.title_crop_rect.as_tuple() if last_title and last_title.title_crop_rect else None,
                "last_title_elapsed_ms": last_title.elapsed_ms if last_title else None,
                "last_title_ocr_boxes": [asdict(box) for box in last_title.ocr_result.boxes] if last_title else [],
                "last_result_job_id": last_result.job_id if last_result else None,
                "last_result_target_app": last_result.target_app if last_result else None,
                "last_result_app_label": last_result.app_label if last_result else None,
                "last_result_image": str(last_result.image_path) if last_result else None,
                "last_result_ocr_image": str(last_result.ocr_image_path) if last_result else None,
                "last_result_crop_rect": last_result.crop_rect.as_tuple() if last_result and last_result.crop_rect else None,
                "last_result_title_elapsed_ms": last_result.title_ocr_elapsed_ms if last_result else None,
                "last_result_content_elapsed_ms": last_result.content_ocr_elapsed_ms if last_result else None,
                "last_result_total_elapsed_ms": last_result.total_elapsed_ms if last_result else None,
                "last_result_page": last_result.page.page_type.value if last_result else None,
                "last_result_page_confidence": last_result.page.confidence if last_result else None,
                "last_result_messages": len(last_result.messages) if last_result else 0,
                "last_result_layout": asdict(last_result.layout) if last_result else None,
                "last_result_ocr_boxes": [asdict(box) for box in last_result.ocr_result.boxes] if last_result else [],
                "last_result_parsed_messages": [asdict(message) for message in last_result.messages] if last_result else [],
            },
            "logs": [asdict(item) for item in self._services.logs.tail(120)],
            "generation_logs": [asdict(item) for item in self._services.generation_logs.tail(40)],
            "reply_feedback": [asdict(item) for item in self._services.reply_feedback.tail(40)],
            "settings_audit": [asdict(item) for item in self._services.settings_audit.tail(40)],
            "diagnostics_files": self._diagnostics_file_payload(),
        }
        redacted_payload = redact_diagnostics_payload(payload)
        (sample_dir / "diagnostics.json").write_text(json.dumps(redacted_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if self._config.privacy.save_debug_screenshots and last_result and last_result.image_path.exists():
            shutil.copy2(last_result.image_path, sample_dir / last_result.image_path.name)
        if self._config.privacy.save_debug_screenshots and last_title and last_title.title_ocr_image_path.exists():
            shutil.copy2(last_title.title_ocr_image_path, sample_dir / last_title.title_ocr_image_path.name)
        self.statusBar().showMessage(f"调试样本已保存：{sample_dir}", 6000)
        self.append_log(f"debug_sample_saved: {sample_dir}")

    def _diagnostics_file_payload(self) -> dict:
        crash_log = diagnostics_log_path("crash")
        ocr_log = diagnostics_log_path("ocr_worker")
        ai_log = diagnostics_log_path("ai_provider")
        return {
            "crash_log": str(crash_log),
            "crash_tail": _tail_lines(crash_log, 40),
            "ocr_worker_log": str(ocr_log),
            "ocr_worker_tail": _tail_lines(ocr_log, 40),
            "ai_provider_log": str(ai_log),
            "ai_provider_tail": _tail_lines(ai_log, 40),
        }

    def _refresh_generation_log_text(self) -> None:
        if self._generation_log_text is None:
            return
        text = "\n\n".join([self._format_generation_log_lines(12), self._format_reply_feedback_lines(12)])
        self._generation_log_text.setText(text)

    def _format_generation_log_lines(self, limit: int) -> str:
        rows = self._services.generation_logs.tail(limit)
        if not rows:
            return "暂无 AI 生成审计。"
        lines = ["AI 生成审计"]
        for row in rows:
            lines.append(
                f"{row.ts} allowed={row.allowed} provider={row.provider} model={row.model or '-'} "
                f"status={row.status} suggestions={row.suggestion_count} risks={row.risk_summary or '-'} "
                f"context={row.context_hash[:12]} page={row.page_type}/{row.page_confidence:.2f} "
                f"messages={row.message_count} memories={row.memory_count}"
            )
        return "\n".join(lines)

    def _format_reply_feedback_lines(self, limit: int) -> str:
        rows = self._services.reply_feedback.tail(limit)
        if not rows:
            return "暂无回复反馈。"
        useful = sum(1 for row in rows if row.feedback == "useful")
        bad = sum(1 for row in rows if row.feedback == "bad")
        lines = [f"回复反馈：count={len(rows)} useful={useful} bad={bad}"]
        for row in rows:
            label = "好用" if row.feedback == "useful" else "不合适"
            lines.append(
                f"{row.ts} feedback={label} provider={row.provider} status={row.status} "
                f"label={row.suggestion_label} risk={row.risk} context={row.context_hash[:12]} "
                f"page={row.page_type} messages={row.message_count} memories={row.memory_count} "
                f"preview={row.suggestion_text_preview}"
            )
        return "\n".join(lines)

    def _readonly_text(self, title: str, content: str) -> QTextEdit:
        text = QTextEdit()
        text.setReadOnly(True)
        text.setText(content)
        return text

    def _fill_table(self, table: QTableWidget, rows: list[tuple[str, ...]]) -> None:
        table.setRowCount(len(rows))
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        for row_index, row in enumerate(rows):
            for col_index, value in enumerate(row):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row_index, col_index, item)
        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)

    def _reload_strategy_table(self) -> None:
        if self._strategy_table is None:
            return
        show_archived = self._strategy_show_archived.isChecked() if self._strategy_show_archived else False
        query = (self._strategy_search.text() if self._strategy_search else "").strip().lower()
        strategies = self._services.strategies.list_all(include_archived=show_archived)
        if query:
            strategies = [
                item for item in strategies
                if query in " ".join([item.name, item.goal, item.mode, item.tone, item.avoid]).lower()
            ]
        self._strategy_table.setRowCount(len(strategies))
        self._strategy_table.setAlternatingRowColors(True)
        self._strategy_table.verticalHeader().setVisible(False)
        for row_index, strategy in enumerate(strategies):
            assigned = self._services.strategies.count_assigned_contacts(strategy.id)
            values = [
                strategy.name,
                strategy.goal,
                strategy.tone,
                "是" if strategy.requires_manual_reply else "否",
                _strategy_status_label(strategy),
                str(assigned),
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, strategy.id)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._strategy_table.setItem(row_index, col_index, item)
        self._strategy_table.resizeColumnsToContents()
        self._strategy_table.horizontalHeader().setStretchLastSection(True)

    def _selected_strategy(self) -> Strategy | None:
        if self._strategy_table is None or self._strategy_table.currentRow() < 0:
            return None
        item = self._strategy_table.item(self._strategy_table.currentRow(), 0)
        if item is None:
            return None
        return self._services.strategies.get(item.data(Qt.ItemDataRole.UserRole))

    def _add_strategy(self) -> None:
        dialog = StrategyDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        self._services.strategies.create(**values)
        self._reload_strategy_table()
        self.append_log(f"strategy_created: {values['name']}")

    def _duplicate_selected_strategy(self) -> None:
        source = self._selected_strategy()
        if source is None:
            self.statusBar().showMessage("请先选择一个分组", 2500)
            return
        dialog = StrategyDialog(self, Strategy(**{**asdict(source), "id": "", "name": f"{source.name} 副本"}))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        self._services.strategies.create(**values)
        self._reload_strategy_table()
        self.append_log(f"strategy_duplicated: source={source.id}, name={values['name']}")

    def _edit_selected_strategy(self) -> None:
        strategy = self._selected_strategy()
        if strategy is None:
            self.statusBar().showMessage("请先选择一个分组", 2500)
            return
        dialog = StrategyDialog(self, strategy)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        updated = Strategy(
            id=strategy.id,
            created_at=strategy.created_at,
            updated_at=strategy.updated_at,
            archived=strategy.archived,
            **values,
        )
        self._services.strategies.update(updated)
        self._reload_strategy_table()
        self.append_log(f"strategy_updated: {strategy.id}")

    def _toggle_selected_strategy_archive(self) -> None:
        strategy = self._selected_strategy()
        if strategy is None:
            self.statusBar().showMessage("请先选择一个分组", 2500)
            return
        if strategy.id in {"default", "manual_protect"} and not strategy.archived:
            self.statusBar().showMessage("内置安全分组不能归档", 3000)
            return
        assigned = self._services.strategies.count_assigned_contacts(strategy.id)
        archived = not strategy.archived
        if archived and assigned > 0:
            confirmed = QMessageBox.question(
                self,
                "归档分组",
                f"有 {assigned} 个聊天对象仍在使用该分组。归档不会删除这些关系，只会从默认列表中收起。是否继续？",
            )
            if confirmed != QMessageBox.StandardButton.Yes:
                return
        self._services.strategies.set_archived(strategy.id, archived)
        if not archived and self._strategy_show_archived:
            self._strategy_show_archived.setChecked(True)
        self._reload_strategy_table()
        self.append_log(f"strategy_archived_changed: {strategy.id} archived={archived}")

    def _on_contact_selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None = None) -> None:
        if current is None:
            return
        contact_id = current.data(Qt.ItemDataRole.UserRole)
        if not contact_id:
            return
        contact = self._services.contacts.get(contact_id)
        if contact is None:
            return
        self._render_contact_detail(contact)

    def _render_contact_detail(self, contact: Contact) -> None:
        messages = self._services.messages.list_for_contact(contact.id, 50)
        memories = self._services.memories.list_for_contact(contact.id)
        aliases = self._services.contacts.list_aliases(contact.id)
        linked_people = self._services.identities.list_people_for_contact(contact.id)
        people_candidates = self._services.identities.find_people_by_alias(contact.display_name)
        strategy = self._services.strategies.get(contact.strategy_id)
        profile = (
            f"聊天对象：{_contact_display_label(contact)}\n"
            f"平台：{contact.platform}\n"
            f"会话类型：{contact.conversation_type.value}\n"
            f"分组：{strategy.name if strategy else contact.strategy_id}\n"
            f"确认等级：{contact.status.value}\n"
            f"云端 AI：{'允许' if contact.allow_cloud_ai else '未允许'}\n"
            f"别名：{', '.join(alias.alias for alias in aliases) or '暂无'}\n"
            f"备注：{contact.remark or '暂无'}\n"
            f"记忆数量：{len(memories)}"
        )
        identity_text = self._format_contact_identity_detail(contact, linked_people, people_candidates)
        chat = "\n".join(f"{message.speaker.value}: {message.text}" for message in messages) or "暂无聊天记录。"
        memory_text = "\n".join(f"[{memory.status.value}/{memory.kind.value}] {memory.content}" for memory in memories) or "暂无记忆。"
        if self._contact_profile_text:
            self._contact_profile_text.setText(profile)
        if self._contact_identity_text:
            self._contact_identity_text.setText(identity_text)
        if self._contact_members_text:
            self._contact_members_text.setText(self._format_group_members_detail(contact))
        if self._contact_chat_text:
            self._contact_chat_text.setText(chat)
        if self._contact_memory_text:
            self._contact_memory_text.setText(memory_text)
        if self._contact_feedback_text:
            self._contact_feedback_text.setText(self._format_contact_feedback_detail(contact))
        self._refresh_overview_data()

    def _show_updated_contact(self, contact: Contact) -> None:
        self._reload_contact_list(contact.id)
        self._render_contact_detail(contact)
        self._sync_floating_content(contact=contact)

    def _format_contact_identity_detail(self, contact, linked_people, people_candidates) -> str:
        lines = [
            f"平台对象：{contact.platform}·{contact.display_name}",
            "",
            "已链接真实身份：",
        ]
        if linked_people:
            for person, link in linked_people:
                aliases = self._services.identities.list_person_aliases(person.id)
                lines.extend(
                    [
                        f"- {person.display_name} · {person.status.value} · verified={link.verified} · confidence={link.confidence:.2f}",
                        f"  aliases={', '.join(alias.alias for alias in aliases) or '暂无'}",
                        f"  id={person.id}",
                    ]
                )
        else:
            lines.append("- 暂无")
        candidate_ids = {person.id for person, _link in linked_people}
        candidates = [person for person in people_candidates if person.id not in candidate_ids]
        lines.extend(["", "同名候选："])
        if candidates:
            for person in candidates[:8]:
                aliases = self._services.identities.list_person_aliases(person.id)
                lines.append(f"- {person.display_name} · {person.status.value} · aliases={', '.join(alias.alias for alias in aliases) or '暂无'} · {person.id}")
        else:
            lines.append("- 暂无")
        return "\n".join(lines)

    def _format_group_members_detail(self, contact: Contact) -> str:
        if contact.conversation_type != ConversationType.GROUP:
            return "仅群聊可用。"
        members = self._services.identities.list_group_members(contact.id)
        if not members:
            return "暂无群成员。可手动添加成员候选，后续 OCR 会逐步补全。"
        lines = [f"群聊：{contact.platform}·{contact.display_name}", "", "成员："]
        for member in members:
            person = self._services.identities.get_person(member.person_id) if member.person_id else None
            platform_contact = self._services.contacts.get(member.platform_contact_id) if member.platform_contact_id else None
            lines.append(
                "- "
                f"{member.member_display_name} · confidence={member.confidence:.2f} · source={member.source} · "
                f"person={person.display_name if person else '未链接'} · "
                f"对象={platform_contact.platform + '·' + platform_contact.display_name if platform_contact else '未链接'}"
            )
        return "\n".join(lines)

    def _format_contact_feedback_detail(self, contact: Contact) -> str:
        rows = self._services.reply_feedback.list_for_contact(contact.id, 20)
        if not rows:
            return "暂无回复反馈。"
        useful = sum(1 for row in rows if row.feedback == "useful")
        bad = sum(1 for row in rows if row.feedback == "bad")
        lines = [f"最近反馈：{len(rows)} 条 · 好用 {useful} · 不合适 {bad}", ""]
        for row in rows:
            label = "好用" if row.feedback == "useful" else "不合适"
            lines.append(
                f"{row.ts} [{label}] {row.suggestion_label} · risk={row.risk} · "
                f"{row.provider}/{row.status} · {row.page_type} · "
                f"消息{row.message_count}/记忆{row.memory_count} · context={row.context_hash[:12]}"
            )
            lines.append(f"  {row.suggestion_text_preview}")
        return "\n".join(lines)

    def _selected_contact(self) -> Contact | None:
        if self._contact_list is None or self._contact_list.currentItem() is None:
            return None
        contact_id = self._contact_list.currentItem().data(Qt.ItemDataRole.UserRole)
        return self._services.contacts.get(contact_id) if contact_id else None

    def _update_selected_contact_status(self, status: ContactStatus) -> None:
        contact = self._current_contact()
        if contact is None:
            self.statusBar().showMessage("请先选择聊天对象", 2500)
            return
        updated = self._services.contacts.update_profile(contact.id, status=status)
        self._show_updated_contact(updated)
        self.append_log(f"contact_status_updated: {updated.id} -> {status.value}")
        self.statusBar().showMessage(f"聊天对象已更新为：{status.value}", 2500)

    def _protect_selected_contact(self) -> None:
        contact = self._current_contact()
        if contact is None:
            self.statusBar().showMessage("请先选择聊天对象", 2500)
            return
        updated = self._services.contacts.update_profile(contact.id, strategy_id="manual_protect", status=ContactStatus.CONFIRMED)
        self._show_updated_contact(updated)
        self.append_log(f"contact_manual_protect_enabled: {updated.id}")
        self.statusBar().showMessage("已进入手动回复保护", 2500)

    def _edit_selected_contact_profile(self) -> None:
        contact = self._current_contact()
        if contact is None:
            self.statusBar().showMessage("请先选择聊天对象", 2500)
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("编辑聊天对象资料")
        dialog.setMinimumWidth(560)
        layout = QVBoxLayout(dialog)
        form = QGridLayout()
        name = QLineEdit(contact.display_name)
        remark = QTextEdit(contact.remark)
        remark.setMinimumHeight(82)
        status = QComboBox()
        status.addItems([item.value for item in ContactStatus if item != ContactStatus.MERGED])
        status.setCurrentText(contact.status.value)
        strategy = QComboBox()
        strategies = self._services.strategies.list_active()
        if contact.strategy_id not in {item.id for item in strategies}:
            current_strategy = self._services.strategies.get(contact.strategy_id)
            if current_strategy is not None:
                strategies.append(current_strategy)
        for item in strategies:
            label = f"{item.name}（已归档）" if item.archived else item.name
            strategy.addItem(label, item.id)
        index = next((i for i, item in enumerate(strategies) if item.id == contact.strategy_id), 0)
        strategy.setCurrentIndex(index)
        allow_cloud_ai = QCheckBox("允许将此聊天对象的上下文发送给第三方 AI Provider")
        allow_cloud_ai.setChecked(contact.allow_cloud_ai)
        for row, (label, widget) in enumerate([
            ("显示名称", name),
            ("确认等级", status),
            ("分组策略", strategy),
            ("云端 AI", allow_cloud_ai),
            ("备注", remark),
        ]):
            form.addWidget(QLabel(label), row, 0, Qt.AlignmentFlag.AlignTop)
            form.addWidget(widget, row, 1)
        form.setColumnStretch(1, 1)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        updated = self._services.contacts.update_profile(
            contact.id,
            display_name=name.text().strip() or contact.display_name,
            status=ContactStatus(status.currentText()),
            strategy_id=strategy.currentData(),
            allow_cloud_ai=allow_cloud_ai.isChecked(),
            remark=remark.toPlainText().strip(),
        )
        self._show_updated_contact(updated)
        self.append_log(f"contact_profile_updated: {updated.id}")

    def _add_alias_to_selected_contact(self) -> None:
        contact = self._current_contact()
        if contact is None:
            self.statusBar().showMessage("请先选择聊天对象", 2500)
            return
        value, ok = QInputDialog.getText(self, "添加对象别名", "别名")
        if not ok:
            return
        alias = self._services.contacts.add_alias(contact.id, value, "manual")
        if alias is None:
            self.statusBar().showMessage("别名不能为空", 2500)
            return
        refreshed = self._services.contacts.get(contact.id)
        if refreshed:
            self._render_contact_detail(refreshed)
        self.append_log(f"contact_alias_added: {contact.id} alias={alias.alias}")

    def _merge_selected_contact(self) -> None:
        source = self._current_contact()
        if source is None:
            self.statusBar().showMessage("请先选择聊天对象", 2500)
            return
        candidates = [item for item in self._services.contacts.list_recent(500) if item.id != source.id and item.platform == source.platform]
        if not candidates:
            self.statusBar().showMessage("没有可合并的目标对象", 3000)
            return
        labels = [f"{item.display_name} · {item.status.value} · {item.id}" for item in candidates]
        selected, ok = QInputDialog.getItem(self, "合并聊天对象", "合并到", labels, 0, False)
        if not ok or not selected:
            return
        target = candidates[labels.index(selected)]
        updated = self._services.contacts.merge_contacts(source.id, target.id)
        self._reload_contact_list(updated.id)
        self._render_contact_detail(updated)
        self.append_log(f"contact_merged: source={source.id}, target={target.id}")
        self.statusBar().showMessage(f"已合并到：{updated.display_name}", 3000)

    def _create_identity_for_selected_contact(self) -> None:
        contact = self._current_contact()
        if contact is None:
            self.statusBar().showMessage("请先选择聊天对象", 2500)
            return
        name, ok = QInputDialog.getText(self, "新建真实身份", "身份名称", text=contact.display_name)
        if not ok:
            return
        name = name.strip()
        if not name:
            self.statusBar().showMessage("身份名称不能为空", 2500)
            return
        person = self._services.identities.create_person(name, source=f"{contact.platform}:{contact.id}", status=IdentityStatus.CONFIRMED)
        self._services.identities.add_person_alias(person.id, contact.display_name, source="contact_display_name")
        self._services.identities.link_contact_to_person(contact.id, person.id, confidence=1.0, source="manual", verified=True)
        self._render_contact_detail(contact)
        self.append_log(f"identity_created_and_linked: contact={contact.id}, person={person.id}")
        self.statusBar().showMessage(f"已链接真实身份：{person.display_name}", 3000)

    def _link_selected_contact_identity(self) -> None:
        contact = self._current_contact()
        if contact is None:
            self.statusBar().showMessage("请先选择聊天对象", 2500)
            return
        candidates = self._services.identities.find_people_by_alias(contact.display_name)
        if not candidates:
            self.statusBar().showMessage("没有同名身份候选，可先新建身份", 3000)
            return
        labels = [f"{person.display_name} · {person.status.value} · {person.id}" for person in candidates]
        selected, ok = QInputDialog.getItem(self, "链接真实身份", "链接到", labels, 0, False)
        if not ok or not selected:
            return
        person = candidates[labels.index(selected)]
        self._services.identities.link_contact_to_person(contact.id, person.id, confidence=1.0, source="manual", verified=True)
        self._render_contact_detail(contact)
        self.append_log(f"identity_linked: contact={contact.id}, person={person.id}")
        self.statusBar().showMessage(f"已链接：{person.display_name}", 3000)

    def _add_alias_to_selected_person(self) -> None:
        contact = self._current_contact()
        if contact is None:
            self.statusBar().showMessage("请先选择聊天对象", 2500)
            return
        linked_people = self._services.identities.list_people_for_contact(contact.id)
        if not linked_people:
            self.statusBar().showMessage("当前对象还没有链接真实身份", 3000)
            return
        labels = [f"{person.display_name} · {person.status.value} · {person.id}" for person, _link in linked_people]
        selected, ok = QInputDialog.getItem(self, "选择真实身份", "身份", labels, 0, False)
        if not ok or not selected:
            return
        person = linked_people[labels.index(selected)][0]
        alias, ok = QInputDialog.getText(self, "添加身份别名", "别名")
        if not ok:
            return
        item = self._services.identities.add_person_alias(person.id, alias, "manual")
        if item is None:
            self.statusBar().showMessage("身份别名不能为空", 2500)
            return
        self._render_contact_detail(contact)
        self.append_log(f"identity_alias_added: person={person.id}, alias={item.alias}")
        self.statusBar().showMessage("身份别名已添加", 2500)

    def _add_member_to_selected_group(self) -> None:
        group = self._current_contact()
        if group is None:
            self.statusBar().showMessage("请先选择聊天对象", 2500)
            return
        if group.conversation_type != ConversationType.GROUP:
            self.statusBar().showMessage("仅群聊支持群成员", 2500)
            return
        name, ok = QInputDialog.getText(self, "添加群成员", "成员昵称")
        if not ok:
            return
        name = name.strip()
        if not name:
            self.statusBar().showMessage("成员昵称不能为空", 2500)
            return
        member = self._services.identities.add_group_member(
            group_contact_id=group.id,
            member_display_name=name,
            confidence=1.0,
            source="manual",
        )
        self._render_contact_detail(group)
        self.append_log(f"group_member_added: group={group.id}, member={member.member_display_name}")
        self.statusBar().showMessage("群成员已添加", 2500)

    def _link_selected_group_member_identity(self) -> None:
        group = self._current_group_or_warn()
        if group is None:
            return
        member = self._choose_group_member(group)
        if member is None:
            return
        candidates = self._services.identities.find_people_by_alias(member.member_display_name)
        if not candidates:
            self.statusBar().showMessage("没有同名身份候选，可先在身份页新建真实身份", 3500)
            return
        labels = [f"{person.display_name} · {person.status.value} · {person.id}" for person in candidates]
        selected, ok = QInputDialog.getItem(self, "链接成员身份", "真实身份", labels, 0, False)
        if not ok or not selected:
            return
        person = candidates[labels.index(selected)]
        updated = self._services.identities.add_group_member(
            group_contact_id=group.id,
            member_display_name=member.member_display_name,
            person_id=person.id,
            platform_contact_id=member.platform_contact_id,
            confidence=1.0,
            source="manual",
        )
        self._render_contact_detail(group)
        self.append_log(f"group_member_person_linked: group={group.id}, member={updated.member_display_name}, person={person.id}")
        self.statusBar().showMessage(f"成员已链接身份：{person.display_name}", 3000)

    def _link_selected_group_member_contact(self) -> None:
        group = self._current_group_or_warn()
        if group is None:
            return
        member = self._choose_group_member(group)
        if member is None:
            return
        candidates = [item for item in self._services.contacts.list_recent(500) if item.id != group.id]
        if not candidates:
            self.statusBar().showMessage("暂无可链接的平台聊天对象", 3000)
            return
        labels = [f"{item.platform}·{item.display_name} · {item.conversation_type.value} · {item.id}" for item in candidates]
        selected, ok = QInputDialog.getItem(self, "链接成员对象", "平台聊天对象", labels, 0, False)
        if not ok or not selected:
            return
        platform_contact = candidates[labels.index(selected)]
        updated = self._services.identities.add_group_member(
            group_contact_id=group.id,
            member_display_name=member.member_display_name,
            person_id=member.person_id,
            platform_contact_id=platform_contact.id,
            confidence=max(member.confidence, 0.9),
            source="manual",
        )
        self._render_contact_detail(group)
        self.append_log(
            f"group_member_contact_linked: group={group.id}, member={updated.member_display_name}, contact={platform_contact.id}"
        )
        self.statusBar().showMessage(f"成员已链接对象：{platform_contact.display_name}", 3000)

    def _current_group_or_warn(self) -> Contact | None:
        group = self._current_contact()
        if group is None:
            self.statusBar().showMessage("请先选择聊天对象", 2500)
            return None
        if group.conversation_type != ConversationType.GROUP:
            self.statusBar().showMessage("仅群聊支持群成员", 2500)
            return None
        return group

    def _choose_group_member(self, group: Contact):
        members = self._services.identities.list_group_members(group.id)
        if not members:
            self.statusBar().showMessage("请先添加群成员", 2500)
            return None
        labels = [f"{member.member_display_name} · {member.source} · {member.id}" for member in members]
        selected, ok = QInputDialog.getItem(self, "选择群成员", "成员", labels, 0, False)
        if not ok or not selected:
            return None
        return members[labels.index(selected)]

    def _export_selected_contact_data(self) -> None:
        contact = self._current_contact()
        if contact is None:
            self.statusBar().showMessage("请先选择聊天对象", 2500)
            return
        try:
            path = self._services.governance.export_contact(contact.id)
        except Exception as exc:
            self.statusBar().showMessage("导出失败", 3000)
            self.append_log(f"contact_export_failed: {contact.id} error={exc}")
            QMessageBox.warning(self, "导出失败", f"无法导出聊天对象数据：\n{exc}")
            return
        self.append_log(f"contact_exported: {contact.id} -> {path}")
        self.statusBar().showMessage(f"已导出：{path}", 6000)
        QMessageBox.information(self, "导出完成", f"聊天对象数据已导出到：\n{path}")

    def _clear_selected_contact_data(self) -> None:
        contact = self._current_contact()
        if contact is None:
            self.statusBar().showMessage("请先选择聊天对象", 2500)
            return
        answer = QMessageBox.question(
            self,
            "清空聊天对象记录",
            (
                f"将清空「{contact.display_name}」的聊天记录、记忆、AI 生成审计和回复反馈。\n\n"
                "对象名称、别名、备注和分组会保留。此操作无法撤销。是否继续？"
            ),
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            result = self._services.governance.clear_contact_data(contact.id)
        except Exception as exc:
            self.statusBar().showMessage("清空失败", 3000)
            self.append_log(f"contact_clear_failed: {contact.id} error={exc}")
            QMessageBox.warning(self, "清空失败", f"无法清空聊天对象记录：\n{exc}")
            return
        self._render_contact_detail(result.contact)
        self.append_log(
            "contact_content_cleared: "
            f"{contact.id} messages={result.messages_deleted} "
            f"memories={result.memories_deleted} generations={result.generation_logs_deleted} "
            f"feedback={result.reply_feedback_deleted}"
        )
        self.statusBar().showMessage("已清空聊天对象记录，对象资料和别名已保留", 4000)

    def _export_all_data(self) -> None:
        try:
            path = self._services.governance.export_all()
        except Exception as exc:
            self.statusBar().showMessage("全局导出失败", 3000)
            self.append_log(f"global_export_failed: {exc}", "warning")
            QMessageBox.warning(self, "全局导出失败", f"无法导出全部数据：\n{exc}")
            return
        self.append_log(f"global_exported: {path}")
        self.statusBar().showMessage(f"已导出：{path}", 6000)
        QMessageBox.information(self, "导出完成", f"全部本地数据已导出到：\n{path}")

    def _clear_all_content(self) -> None:
        answer = QMessageBox.question(
            self,
            "清空全部内容",
            (
                "将删除所有聊天对象、身份、群成员、聊天记录、记忆、AI 生成审计和回复反馈。\n\n"
                "分组策略、区域校准、设置审计和配置文件会保留。此操作无法撤销。是否继续？"
            ),
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            result = self._services.governance.clear_all_content()
        except Exception as exc:
            self.statusBar().showMessage("清空失败", 3000)
            self.append_log(f"global_clear_failed: {exc}", "warning")
            QMessageBox.warning(self, "清空失败", f"无法清空全部内容：\n{exc}")
            return
        self._reload_contact_list()
        self._refresh_overview_data()
        self.append_log(
            "global_content_cleared: "
            f"contacts={result.contacts_deleted} messages={result.messages_deleted} "
            f"memories={result.memories_deleted} generations={result.generation_logs_deleted} "
            f"feedback={result.reply_feedback_deleted}"
        )
        self.statusBar().showMessage("全部内容已清空，设置和审计已保留", 5000)

    def _run_retention_cleanup(self) -> None:
        before = _redacted_config_snapshot(self._config)
        self._sync_retention_config_from_ui()
        secret_backend = self._config_store.save(self._config)
        changes = _config_changes(before, _redacted_config_snapshot(self._config))
        if changes:
            self._services.settings_audit.append(
                actor="local_user",
                scope="retention",
                changes=changes,
                secret_backend=secret_backend,
            )
        try:
            result = self._services.retention.cleanup(self._config.privacy)
        except Exception as exc:
            self.statusBar().showMessage("本地清理失败", 3000)
            self.append_log(f"retention_cleanup_failed: {exc}", "warning")
            QMessageBox.warning(self, "本地清理失败", f"无法清理过期文件：\n{exc}")
            return
        self.append_log(
            "retention_cleanup_completed: "
            f"files={result.files_deleted} dirs={result.dirs_deleted} bytes={result.bytes_deleted} "
            f"records={result.records_deleted}"
        )
        self.statusBar().showMessage(
            f"已清理 {result.files_deleted} 个文件、{result.records_deleted} 条记录，释放 {result.bytes_deleted // 1024} KB",
            4000,
        )
        if self._diagnostics_file_text is not None:
            self._diagnostics_file_text.setText(self._format_diagnostics_files())
        self._refresh_generation_log_text()
        contact = self._current_contact()
        if contact is not None:
            self._render_contact_detail(contact)

    def _build_memory_review_tab(self, status: MemoryStatus) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        memories = self._services.memories.list_by_status(status)
        if not memories:
            layout.addWidget(self._readonly_text(status.value, "暂无数据。"))
            return container
        for memory in memories:
            layout.addWidget(self._memory_row(memory, status))
        layout.addStretch(1)
        return container

    def _memory_row(self, memory: Memory, status: MemoryStatus) -> QWidget:
        row = QFrame()
        row.setObjectName("MetricCard")
        layout = QGridLayout(row)
        layout.setContentsMargins(10, 8, 10, 8)
        contact = self._services.contacts.get(memory.contact_id)
        title = QLabel(f"{contact.display_name if contact else '未知联系人'} · {memory.kind.value}")
        title.setObjectName("SectionTitle")
        content = QLabel(memory.content)
        content.setWordWrap(True)
        meta = QLabel(f"confidence={memory.confidence if memory.confidence is not None else '-'} · {memory.created_at}")
        meta.setObjectName("TinyMuted")
        layout.addWidget(title, 0, 0, 1, 2)
        layout.addWidget(content, 1, 0, 1, 2)
        layout.addWidget(meta, 2, 0)
        if status == MemoryStatus.PENDING:
            confirm = QPushButton("确认")
            confirm.clicked.connect(lambda checked=False, memory_id=memory.id: self._set_memory_status(memory_id, MemoryStatus.CONFIRMED))
            reject = QPushButton("拒绝")
            reject.clicked.connect(lambda checked=False, memory_id=memory.id: self._set_memory_status(memory_id, MemoryStatus.REJECTED))
            layout.addWidget(confirm, 0, 2)
            layout.addWidget(reject, 1, 2)
        layout.setColumnStretch(1, 1)
        return row

    def _set_memory_status(self, memory_id: str, status: MemoryStatus) -> None:
        memory = self._services.memories.update_status(memory_id, status)
        if self._memory_tabs is not None:
            current = self._memory_tabs.currentIndex()
            self._memory_tabs.clear()
            self._memory_tabs.addTab(self._build_memory_review_tab(MemoryStatus.PENDING), "待确认")
            self._memory_tabs.addTab(self._build_memory_review_tab(MemoryStatus.CONFIRMED), "长期画像")
            self._memory_tabs.addTab(self._build_memory_review_tab(MemoryStatus.REJECTED), "已拒绝")
            self._memory_tabs.setCurrentIndex(min(current, self._memory_tabs.count() - 1))
        contact = self._services.contacts.get(memory.contact_id)
        if contact is not None:
            self._show_updated_contact(contact)
        self.append_log(f"memory_status_updated: {memory_id} -> {status.value}")
        self.statusBar().showMessage(f"记忆已更新为：{status.value}", 2500)

    def _open_calibration_dialog(self) -> None:
        state = self._services.runtime.state
        if state.layout is None or state.window.rect is None:
            self.statusBar().showMessage("当前没有可校准的微信窗口区域", 3000)
            self.append_log("calibration_open_failed: no layout", "warning")
            return
        screenshot_path = self._capture_calibration_screenshot(state)
        dialog = CalibrationDialog(self, state.layout, screenshot_path)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        calibration = self._services.calibrations.create_from_layout(
            name=values["name"],
            target=TargetApp.WECHAT,
            window_rect=state.window.rect,
            layout=values["layout"],
            theme=values["theme"],
            active=True,
        )
        refreshed = self._services.runtime.refresh_current()
        self.update_runtime_state(refreshed)
        self.append_log(f"layout_calibration_saved: {calibration.id} name={calibration.name}")
        self.statusBar().showMessage("区域校准已保存并启用", 3000)

    def _capture_calibration_screenshot(self, state: RuntimeState) -> Path | None:
        if state.window.rect is None:
            return None
        output = app_data_dir() / "calibration" / "current_window.png"
        try:
            return capture_rect(state.window.rect.as_tuple(), output)
        except Exception as exc:
            self.append_log(f"calibration_screenshot_unavailable: {exc}", "warning")
            return None

    def _run_capture_pipeline(self) -> None:
        state = self._services.runtime.state
        job_id = self._services.pipeline.submit(self._services.runtime.state)
        if job_id is None:
            summary = self._manual_capture_block_summary(state)
            self.statusBar().showMessage(summary, 6000)
            self.append_log(f"capture_pipeline_submit_skipped: {summary}", "warning")
            if self._runtime_text is not None:
                self._runtime_text.setText(self._format_runtime_state(self._services.runtime.state))
            if self._window_match_text is not None:
                self._window_match_text.setText(self._format_window_match_diagnostics())
            return
        self.statusBar().showMessage(f"采集管线已启动：job={job_id}", 2500)
        self.append_log(f"capture_pipeline_submitted: job={job_id}")

    def _manual_capture_block_summary(self, state: RuntimeState) -> str:
        discard = self._services.pipeline.last_discard_reason or "-"
        if state.window.state.value != "visible":
            return f"采集未启动：窗口 {state.window.state.value}；{state.window.diagnostic or state.capture_decision.reason}"
        if state.layout is None:
            return f"采集未启动：区域不可用；{state.page.reason}"
        if not state.capture_decision.should_capture:
            return f"采集未启动：{state.capture_decision.reason}；discard={discard}"
        if self._services.pipeline.is_running:
            return f"采集未启动：上一轮采集仍在运行；discard={discard}"
        return f"采集未启动：{discard}"

    def _refresh_target_grid(self) -> None:
        if self._target_grid is None:
            return
        pending = {
            target.app_id: (
                self._target_checkboxes[target.app_id].isChecked() if target.app_id in self._target_checkboxes else target.enabled,
                self._target_process_inputs[target.app_id].text() if target.app_id in self._target_process_inputs else ", ".join(target.process_names),
                self._target_title_inputs[target.app_id].text() if target.app_id in self._target_title_inputs else ", ".join(target.title_keywords),
                self._target_exclude_title_inputs[target.app_id].text()
                if target.app_id in self._target_exclude_title_inputs
                else ", ".join(target.exclude_title_keywords),
            )
            for target in self._config.targets
        }
        while self._target_grid.count():
            item = self._target_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._target_checkboxes = {}
        self._target_process_inputs = {}
        self._target_title_inputs = {}
        self._target_exclude_title_inputs = {}
        for col, label in enumerate(["启用", "应用", "进程名", "标题关键词", "排除标题", ""]):
            header = QLabel(label)
            header.setObjectName("TinyMuted")
            self._target_grid.addWidget(header, 0, col)
        for row, target in enumerate(self._config.targets):
            checked, process_text, title_text, exclude_title_text = pending.get(
                target.app_id,
                (
                    target.enabled,
                    ", ".join(target.process_names),
                    ", ".join(target.title_keywords),
                    ", ".join(target.exclude_title_keywords),
                ),
            )
            checkbox = QCheckBox(target.label)
            checkbox.setChecked(checked)
            process_input = QLineEdit(process_text)
            title_input = QLineEdit(title_text)
            exclude_title_input = QLineEdit(exclude_title_text)
            self._target_checkboxes[target.app_id] = checkbox
            self._target_process_inputs[target.app_id] = process_input
            self._target_title_inputs[target.app_id] = title_input
            self._target_exclude_title_inputs[target.app_id] = exclude_title_input
            self._target_grid.addWidget(checkbox, row + 1, 0)
            self._target_grid.addWidget(QLabel(target.label), row + 1, 1)
            self._target_grid.addWidget(process_input, row + 1, 2)
            self._target_grid.addWidget(title_input, row + 1, 3)
            self._target_grid.addWidget(exclude_title_input, row + 1, 4)
            if target.app_id.startswith("custom_"):
                remove = QPushButton("删除")
                remove.setObjectName("DangerButton")
                remove.clicked.connect(lambda _checked=False, app_id=target.app_id: self._remove_target_app(app_id))
                self._target_grid.addWidget(remove, row + 1, 5)

    def _add_target_app(self) -> None:
        dialog = TargetAppDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        app_id = _unique_target_app_id(values["app_id"], [target.app_id for target in self._config.targets])
        self._config.targets.append(
            TargetWindowConfig(
                app_id=app_id,
                label=values["label"],
                enabled=True,
                process_names=values["process_names"],
                title_keywords=values["title_keywords"],
                exclude_title_keywords=values["exclude_title_keywords"],
            )
        )
        self._refresh_target_grid()
        self.append_log(f"target_app_added: {app_id}")

    def _remove_target_app(self, app_id: str) -> None:
        self._config.targets = [target for target in self._config.targets if target.app_id != app_id or not target.app_id.startswith("custom_")]
        self._refresh_target_grid()
        self.append_log(f"target_app_removed: {app_id}")

    def _save_ai_settings(self) -> None:
        parsed_targets = self._target_configs_from_ui()
        if parsed_targets is None:
            return
        validation_error = self._settings_validation_error(parsed_targets)
        if validation_error:
            self.statusBar().showMessage(validation_error, 5000)
            self.append_log(f"settings_save_failed: {validation_error}", "warning")
            return
        before = _redacted_config_snapshot(self._config)
        previous_api_key = self._config.ai.api_key
        submitted_api_key = self._ai_api_key.text()
        self._config.ai.provider = self._ai_provider.currentText()
        self._config.ai.base_url = self._ai_base_url.text().strip()
        self._config.ai.model = self._ai_model.text().strip()
        self._config.ai.api_key = submitted_api_key
        self._config.ai.temperature = self._ai_temperature.value()
        self._config.ai.context_tokens = self._ai_context_tokens.value()
        self._config.ai.timeout_seconds = self._ai_timeout.value()
        self._config.ai.request_cooldown_seconds = self._ai_request_cooldown.value() if self._ai_request_cooldown else 8
        self._config.ai.dedupe_context_minutes = self._ai_dedupe_minutes.value() if self._ai_dedupe_minutes else 30
        self._config.ai.max_daily_cloud_requests = self._ai_daily_limit.value() if self._ai_daily_limit else 100
        self._config.ai.failure_backoff_threshold = self._ai_failure_threshold.value() if self._ai_failure_threshold else 3
        self._config.ai.failure_backoff_minutes = self._ai_failure_backoff.value() if self._ai_failure_backoff else 5
        self._config.privacy.enable_long_term_memory = self._privacy_long_memory.isChecked() if self._privacy_long_memory else True
        self._config.privacy.save_debug_screenshots = self._privacy_debug_screenshots.isChecked() if self._privacy_debug_screenshots else False
        self._config.privacy.trim_context_for_cloud = self._privacy_trim_cloud.isChecked() if self._privacy_trim_cloud else True
        self._config.privacy.require_cloud_prompt_review = self._privacy_cloud_review.isChecked() if self._privacy_cloud_review else True
        self._config.privacy.manual_protection_blocks_replies = self._privacy_manual_blocks.isChecked() if self._privacy_manual_blocks else True
        self._sync_retention_config_from_ui()
        self._config.ocr.provider = self._ocr_provider.currentText() if self._ocr_provider else "Preview Fixture"
        self._config.ocr.language = self._ocr_language.text().strip() if self._ocr_language else "ch"
        self._config.ocr.min_confidence = self._ocr_min_confidence.value() if self._ocr_min_confidence else 0.5
        self._config.ocr.use_gpu = self._ocr_use_gpu.isChecked() if self._ocr_use_gpu else False
        self._config.capture.scroll_debounce_ms = self._capture_debounce.value() if self._capture_debounce else 500
        self._config.capture.ocr_min_interval_ms = self._capture_ocr_interval.value() if self._capture_ocr_interval else 8000
        self._config.capture.auto_capture_enabled = self._capture_auto_enabled.isChecked() if self._capture_auto_enabled else True
        self._config.capture.pause_ai_on_unknown_page = self._capture_pause_unknown.isChecked() if self._capture_pause_unknown else True
        self._config.capture.block_memory_for_unconfirmed_contact = (
            self._capture_block_unconfirmed.isChecked() if self._capture_block_unconfirmed else True
        )
        self._config.floating.placement_preference = self._floating_placement.currentText() if self._floating_placement else "auto"
        self._config.floating.opacity_percent = self._floating_opacity.value() if self._floating_opacity else 96
        self._config.floating.suggestion_count = self._floating_suggestion_count.value() if self._floating_suggestion_count else 3
        self._config.targets = parsed_targets
        self._services.autocapture.set_enabled(self._config.capture.auto_capture_enabled)
        self._services.runtime.capture_gate.policy = replace(
            self._services.runtime.capture_gate.policy,
            scroll_debounce_ms=self._config.capture.scroll_debounce_ms,
            ocr_min_interval_ms=self._config.capture.ocr_min_interval_ms,
        )
        old_ocr_shutdown = getattr(self._services.pipeline.ocr_engine, "shutdown", None)
        if callable(old_ocr_shutdown):
            try:
                old_ocr_shutdown()
            except Exception as exc:
                self.append_log(f"ocr_engine_shutdown_failed_before_switch: {exc}", "warning")
        self._services.pipeline.ocr_engine = create_ocr_engine(self._config.ocr)
        if self._floating is not None and hasattr(self._floating, "apply_preferences"):
            self._floating.apply_preferences(
                placement_preference=self._config.floating.placement_preference,
                opacity_percent=self._config.floating.opacity_percent,
                suggestion_count=self._config.floating.suggestion_count,
            )
        self.targets_changed.emit(self._config.targets)
        secret_backend = self._config_store.save(self._config)
        changes = _config_changes(before, _redacted_config_snapshot(self._config))
        if previous_api_key != self._config.ai.api_key or submitted_api_key:
            changes["ai.api_key"] = {
                "old": "<set>" if previous_api_key else "<empty>",
                "new": "<set>" if self._config.ai.api_key else "<empty>",
                "changed": previous_api_key != self._config.ai.api_key,
                "submitted": bool(submitted_api_key),
            }
        if changes:
            self._services.settings_audit.append(
                actor="local_user",
                scope="settings",
                changes=changes,
                secret_backend=secret_backend,
            )
        if self._ai_status_value is not None:
            value = self._config.ai.model if self._config.ai.provider != "Disabled" else "已禁用"
            self._ai_status_value.setText(value)
        if self._ai_health_label is not None:
            self._ai_health_label.setText(self._services.reply_generator.provider_health_summary())
        self.append_log(
            f"ai_settings_saved: provider={self._config.ai.provider}, model={self._config.ai.model}, "
            f"changes={len(changes)}, secret_backend={secret_backend}"
        )
        if secret_backend == "unavailable":
            self.statusBar().showMessage("AI 设置已保存，但密钥安全存储不可用", 4000)
        else:
            self.statusBar().showMessage("AI 设置已保存", 3000)

    def _settings_validation_error(self, parsed_targets: list[TargetWindowConfig]) -> str:
        provider = self._ai_provider.currentText() if self._ai_provider else self._config.ai.provider
        base_url = self._ai_base_url.text().strip() if self._ai_base_url else ""
        model = self._ai_model.text().strip() if self._ai_model else ""
        if provider in {"OpenAI", "OpenAI Compatible"}:
            if not base_url.startswith(("http://", "https://")):
                return "云端 AI 接口地址必须以 http:// 或 https:// 开头"
            if not model:
                return "云端 AI 模型名称不能为空"
        elif provider == "Local Model" and not model:
            return "本地模型名称不能为空"
        ocr_language = self._ocr_language.text().strip() if self._ocr_language else "ch"
        if not ocr_language:
            return "OCR 语言不能为空"
        if not any(target.enabled for target in parsed_targets):
            return "至少启用一个目标聊天应用"
        return ""

    def _reset_ai_provider_health(self) -> None:
        summary = self._services.reply_generator.reset_provider_health("manual_ui")
        if self._ai_health_label is not None:
            self._ai_health_label.setText(summary)
        self._services.logs.append(
            "warning",
            "ai",
            "provider_health_reset",
            "AI Provider health state reset by user",
            {"summary": summary},
        )
        self.append_log(f"ai_provider_health_reset: {summary}", "warning")
        self.statusBar().showMessage("AI Provider 健康状态已恢复", 3000)

    def _sync_retention_config_from_ui(self) -> None:
        self._config.privacy.diagnostic_log_retention_days = self._privacy_log_retention.value() if self._privacy_log_retention else 14
        self._config.privacy.debug_sample_retention_days = self._privacy_debug_retention.value() if self._privacy_debug_retention else 14
        self._config.privacy.capture_retention_days = self._privacy_capture_retention.value() if self._privacy_capture_retention else 7
        self._config.privacy.calibration_retention_days = self._privacy_calibration_retention.value() if self._privacy_calibration_retention else 30
        self._config.privacy.reply_feedback_retention_days = self._privacy_feedback_retention.value() if self._privacy_feedback_retention else 180

    def _target_configs_from_ui(self) -> list[TargetWindowConfig] | None:
        result: list[TargetWindowConfig] = []
        for target in self._config.targets:
            checkbox = self._target_checkboxes.get(target.app_id)
            process_input = self._target_process_inputs.get(target.app_id)
            title_input = self._target_title_inputs.get(target.app_id)
            exclude_title_input = self._target_exclude_title_inputs.get(target.app_id)
            enabled = checkbox.isChecked() if checkbox is not None else target.enabled
            process_names = _split_match_rules(process_input.text()) if process_input is not None else list(target.process_names)
            title_keywords = _split_match_rules(title_input.text()) if title_input is not None else list(target.title_keywords)
            exclude_title_keywords = (
                _split_match_rules(exclude_title_input.text())
                if exclude_title_input is not None
                else list(target.exclude_title_keywords)
            )
            if enabled and not process_names and not title_keywords:
                self.statusBar().showMessage(f"{target.label} 已启用但缺少匹配规则", 4000)
                self.append_log(f"settings_save_failed: target_without_rules app={target.app_id}", "warning")
                return None
            result.append(
                TargetWindowConfig(
                    app_id=target.app_id,
                    label=target.label,
                    enabled=enabled,
                    process_names=process_names,
                    title_keywords=title_keywords,
                    exclude_title_keywords=exclude_title_keywords,
                )
            )
        return result

    def _test_ai_settings(self) -> None:
        config = replace(
            self._config,
            ai=replace(
                self._config.ai,
                provider=self._ai_provider.currentText(),
                base_url=self._ai_base_url.text().strip(),
                model=self._ai_model.text().strip(),
                api_key=self._ai_api_key.text(),
                temperature=self._ai_temperature.value(),
                context_tokens=self._ai_context_tokens.value(),
                timeout_seconds=self._ai_timeout.value(),
            ),
        )
        result = test_ai_connection(config)
        level = "info" if result.ok else "warning"
        self.statusBar().showMessage(result.detail, 5000)
        self.append_log(
            f"ai_settings_test_{'passed' if result.ok else 'failed'}: "
            f"provider={result.provider} status={result.status} elapsed_ms={result.elapsed_ms}",
            level,
        )
