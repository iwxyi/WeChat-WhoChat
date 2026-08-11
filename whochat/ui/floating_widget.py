from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from whochat.ai.models import ReplyGenerationResult


@dataclass(frozen=True)
class Placement:
    x: int
    y: int
    width: int
    height: int
    edge: str


class FloatingWidget(QWidget):
    suggestion_copied = Signal(str)
    user_hidden_changed = Signal(bool)

    GAP = 6
    MIN_WIDTH = 520
    MAX_WIDTH = 880
    BAR_HEIGHT = 40
    SIDE_WIDTH = 380
    SIDE_HEIGHT = 40

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setObjectName("FloatingWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._drag_pos = None
        self._user_hidden = False
        self._last_rect: tuple[int, int, int, int] | None = None
        self._last_title = "微信"
        self._last_edge = ""
        self._placement_preference = "auto"
        self._suggestion_count = 3

        root = QFrame()
        root.setObjectName("FloatingRoot")
        shell = QHBoxLayout(root)
        shell.setContentsMargins(8, 6, 8, 6)
        shell.setSpacing(6)
        self.contact_label = QLabel("未确认联系人")
        self.contact_label.setObjectName("FloatingContact")
        self.contact_label.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)
        self.group_label = QLabel("默认分组")
        self.group_label.setObjectName("FloatingBadge")
        self.group_label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.group_label.setVisible(False)
        self.status_label = QLabel("等待")
        self.status_label.setObjectName("FloatingStatus")
        self.status_label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        hide_button = QPushButton("×")
        hide_button.setObjectName("FloatingGhostButton")
        hide_button.setToolTip("隐藏悬浮窗")
        hide_button.setFixedSize(26, 26)
        hide_button.clicked.connect(self.hide_by_user)
        self.suggestion_buttons: list[QPushButton] = []
        shell.addWidget(self.contact_label)
        shell.addWidget(self.group_label)
        shell.addWidget(self.status_label)
        shell.addStretch(1)
        self._set_suggestions(
            [
                ("回复1", "收到，我先确认关键信息，稍后给你明确回复。"),
                ("回复2", "明白，我看一下后回复你。"),
                ("回复3", "这个我需要先评估时间和影响，再准确答复。"),
            ]
        )
        for button in self.suggestion_buttons:
            shell.addWidget(button)
        shell.addWidget(hide_button)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(root)

        self._place_on_primary_screen()

    @property
    def user_hidden(self) -> bool:
        return self._user_hidden

    @property
    def placement_preference(self) -> str:
        return self._placement_preference

    @property
    def suggestion_count(self) -> int:
        return self._suggestion_count

    @property
    def placement_edge(self) -> str:
        return self._last_edge

    def apply_preferences(self, *, placement_preference: str = "auto", opacity_percent: int = 96, suggestion_count: int = 3) -> None:
        placement = placement_preference if placement_preference in {"auto", "bottom", "top", "right", "left"} else "auto"
        self._placement_preference = placement
        self._suggestion_count = self._clamp(suggestion_count, 1, 3)
        self.setWindowOpacity(self._clamp(opacity_percent, 70, 100) / 100)
        for index, button in enumerate(self.suggestion_buttons):
            button.setVisible(index < self._suggestion_count)
        if self._last_rect is not None and not self._user_hidden:
            self.attach_to_window_rect(self._last_rect, self._last_title)

    def update_context(self, *, contact_name: str, group_name: str, status: str, action: str = "", app_label: str = "微信") -> None:
        self.contact_label.setText(_context_label(app_label, contact_name, group_name))
        self.contact_label.setToolTip(_context_label(app_label, contact_name, group_name, max_len=120))
        self.group_label.setText(group_name or "默认分组")
        self.status_label.setText(status or "等待")
        self.status_label.setToolTip(action or status or "等待")

    def update_reply_result(self, result: ReplyGenerationResult) -> None:
        if result.status.startswith("reply_pending"):
            self.status_label.setText("生成中")
            self._update_suggestion_buttons([], enabled=False)
            return
        if not result.allowed:
            self.status_label.setText(_short_status(result.status))
            self._update_suggestion_buttons([], enabled=False)
            return
        self.status_label.setText(_risk_status(result))
        suggestions = [(item.label or f"回复{index + 1}", item.text) for index, item in enumerate(result.suggestions[:3])]
        self._update_suggestion_buttons(suggestions, enabled=True)

    def disable_suggestions(self) -> None:
        self._update_suggestion_buttons([], enabled=False)

    def show_waiting(self) -> None:
        self._user_hidden = False
        self.user_hidden_changed.emit(False)
        self.contact_label.setText("微信·未确认联系人（默认分组）")
        self.group_label.setText("默认分组")
        self.status_label.setText("等待微信")
        self._place_on_primary_screen()
        self.show()

    def show_by_user(self) -> None:
        self._user_hidden = False
        self.user_hidden_changed.emit(False)
        if self._last_rect is not None:
            self.attach_to_window_rect(self._last_rect, self._last_title)
        else:
            self.show_waiting()

    def hide_by_user(self) -> None:
        self._user_hidden = True
        self.user_hidden_changed.emit(True)
        self.hide()

    def attach_to_window_rect(self, rect: tuple[int, int, int, int], title: str = "微信") -> None:
        self._last_rect = rect
        self._last_title = title
        placement = self._choose_placement(rect)
        if placement is None:
            self.status_label.setText("空间不足")
            if not self._user_hidden:
                self.hide()
            return

        self.setFixedSize(placement.width, placement.height)
        self.move(placement.x, placement.y)
        self._last_edge = placement.edge
        existing_tip = self.status_label.toolTip().strip()
        placement_tip = f"悬浮窗已贴靠目标窗口{placement.edge}"
        self.status_label.setToolTip(f"{existing_tip}\n{placement_tip}".strip() if existing_tip else placement_tip)
        if not self._user_hidden and not self.isVisible():
            self.show()

    def detach_from_window(self, reason: str) -> None:
        self._last_rect = None
        self._last_edge = ""
        self.contact_label.setText("未确认联系人")
        self.group_label.setText("默认分组")
        self.status_label.setText(reason)
        if not self._user_hidden and not self.isVisible():
            self.show()

    def hide_for_window_state(self, reason: str) -> None:
        self._last_rect = None
        self._last_edge = ""
        self.contact_label.setText("未确认联系人")
        self.group_label.setText("默认分组")
        self.status_label.setText(reason)
        if not self._user_hidden:
            self.hide()

    def _set_suggestions(self, suggestions: list[tuple[str, str]]) -> None:
        self.suggestion_buttons = [self._suggestion_button(label, text) for label, text in suggestions[:3]]

    def _update_suggestion_buttons(self, suggestions: list[tuple[str, str]], *, enabled: bool) -> None:
        fallback = [(f"回复{index + 1}", "") for index in range(3)]
        values = (suggestions + fallback)[:3]
        for index, (button, (label, text)) in enumerate(zip(self.suggestion_buttons, values)):
            button.setText(_clip_label(label))
            button.setToolTip(text if text else "当前没有可复制的建议")
            button.setProperty("reply_text", text)
            button.setEnabled(enabled and bool(text) and index < self._suggestion_count)
            button.setVisible(index < self._suggestion_count)

    def _suggestion_button(self, label: str, text: str) -> QWidget:
        button = QPushButton(label)
        button.setObjectName("FloatingSuggestionButton")
        button.setToolTip(text)
        button.setProperty("reply_text", text)
        button.setFixedHeight(28)
        button.clicked.connect(lambda checked=False, target=button: self._copy(str(target.property("reply_text") or "")))
        return button

    def _copy(self, text: str) -> None:
        if not text:
            self.status_label.setText("无建议")
            return
        QApplication.clipboard().setText(text)
        self.status_label.setText("已复制")
        self.suggestion_copied.emit(text)

    def _choose_placement(self, rect: tuple[int, int, int, int]) -> Placement | None:
        left, top, right, bottom = rect
        screen = QGuiApplication.screenAt(QPoint((left + right) // 2, (top + bottom) // 2))
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return None
        area = screen.availableGeometry()
        window_width = max(1, right - left)
        bar_width = min(self.MAX_WIDTH, max(self.MIN_WIDTH, min(window_width, self.MAX_WIDTH)))
        centered_x = self._clamp(left + (window_width - bar_width) // 2, area.left(), area.right() - bar_width + 1)
        side_y = self._clamp(top + 72, area.top(), area.bottom() - self.SIDE_HEIGHT + 1)

        def bottom_placement() -> Placement | None:
            bottom_y = bottom + self.GAP
            if bottom_y + self.BAR_HEIGHT <= area.bottom() + 1:
                return Placement(centered_x, bottom_y, bar_width, self.BAR_HEIGHT, "底部")
            return None

        def top_placement() -> Placement | None:
            top_y = top - self.GAP - self.BAR_HEIGHT
            if top_y >= area.top():
                return Placement(centered_x, top_y, bar_width, self.BAR_HEIGHT, "顶部")
            return None

        def right_placement() -> Placement | None:
            right_x = right + self.GAP
            if right_x + self.SIDE_WIDTH <= area.right() + 1:
                return Placement(right_x, side_y, self.SIDE_WIDTH, self.SIDE_HEIGHT, "右侧")
            return None

        def left_placement() -> Placement | None:
            left_x = left - self.GAP - self.SIDE_WIDTH
            if left_x >= area.left():
                return Placement(left_x, side_y, self.SIDE_WIDTH, self.SIDE_HEIGHT, "左侧")
            return None

        candidates = {
            "bottom": bottom_placement,
            "top": top_placement,
            "right": right_placement,
            "left": left_placement,
        }
        order = ["bottom", "top", "right", "left"]
        if self._placement_preference != "auto":
            order = [self._placement_preference, *[item for item in order if item != self._placement_preference]]
        for key in order:
            placement = candidates[key]()
            if placement is not None:
                return placement

        return None

    def _place_on_primary_screen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if not screen:
            return
        area = screen.availableGeometry()
        self.setFixedSize(min(self.MAX_WIDTH, area.width()), self.BAR_HEIGHT)
        self.move(area.left() + (area.width() - self.width()) // 2, area.bottom() - self.height() + 1)

    @staticmethod
    def _clamp(value: int, low: int, high: int) -> int:
        if high < low:
            return low
        return max(low, min(value, high))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_pos = None
        event.accept()


def _clip_label(value: str) -> str:
    value = value.strip() or "回复"
    return value if len(value) <= 6 else value[:5] + "…"


def _context_label(app_label: str, contact_name: str, group_name: str, max_len: int = 34) -> str:
    app = (app_label or "聊天").strip()
    contact = (contact_name or "未确认联系人").strip()
    group = (group_name or "默认分组").strip()
    text = f"{app}·{contact}（{group}）"
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def _short_status(value: str) -> str:
    if value.startswith("blocked:provider_backoff"):
        return "AI退避"
    if value.startswith("blocked:"):
        return "已阻断"
    if "失败" in value:
        return "失败"
    return "待确认"


def _risk_status(result: ReplyGenerationResult) -> str:
    risks = {item.risk.lower() for item in result.suggestions}
    if "high" in risks:
        return "高风险"
    if "medium" in risks:
        return "中风险"
    return "可复制"
