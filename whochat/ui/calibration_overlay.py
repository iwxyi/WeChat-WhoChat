from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from whochat.core.runtime import LayoutRegions, Rect
from whochat.ocr.models import OcrResult


REGION_LABELS = {
    "nav": "导航",
    "chat_list": "聊天列表",
    "title": "标题",
    "message": "聊天记录",
    "input": "输入区",
}

REGION_COLORS = {
    "nav": QColor(25, 118, 210, 96),
    "chat_list": QColor(15, 118, 110, 96),
    "title": QColor(123, 97, 255, 86),
    "message": QColor(245, 158, 11, 82),
    "input": QColor(220, 38, 38, 76),
}


class CalibrationCanvas(QWidget):
    layout_changed = Signal(object)

    def __init__(self, layout: LayoutRegions, screenshot: QPixmap | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = layout
        self._screenshot = screenshot
        self._ocr_result: OcrResult | None = None
        self._drag_region: str | None = None
        self._drag_start: QPoint | None = None
        self._drag_start_rect: Rect | None = None
        self.setMinimumSize(760, 430)
        self.setMouseTracking(True)

    @property
    def layout_regions(self) -> LayoutRegions:
        return self._layout

    def set_layout_regions(self, layout: LayoutRegions) -> None:
        self._layout = layout
        self.layout_changed.emit(layout)
        self.update()

    def set_ocr_result(self, result: OcrResult | None) -> None:
        self._ocr_result = result
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#f4f6f8"))
        canvas = self._canvas_rect()
        painter.fillRect(canvas, QColor("#ffffff"))
        if self._screenshot and not self._screenshot.isNull():
            painter.drawPixmap(canvas, self._screenshot)
        else:
            painter.setPen(QColor("#9aa5b1"))
            painter.drawText(canvas, Qt.AlignmentFlag.AlignCenter, "当前环境未提供截图，使用区域示意图校准")
        painter.setPen(QPen(QColor("#cbd2d9"), 1))
        painter.drawRect(canvas)

        for key, source_rect in self._region_rects().items():
            screen_rect = self._to_canvas_rect(source_rect, canvas)
            painter.fillRect(screen_rect, REGION_COLORS[key])
            pen = QPen(REGION_COLORS[key].darker(160), 2)
            painter.setPen(pen)
            painter.drawRect(screen_rect)
            painter.setFont(QFont(painter.font().family(), 9, QFont.Weight.Bold))
            painter.setPen(QColor("#102a43"))
            label_rect = QRect(screen_rect.left() + 6, screen_rect.top() + 5, max(60, screen_rect.width() - 12), 20)
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, REGION_LABELS[key])
        if self._ocr_result:
            self._paint_ocr_boxes(painter, canvas)
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        canvas = self._canvas_rect()
        for key, source_rect in reversed(list(self._region_rects().items())):
            if self._to_canvas_rect(source_rect, canvas).contains(event.position().toPoint()):
                self._drag_region = key
                self._drag_start = event.position().toPoint()
                self._drag_start_rect = source_rect
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                return

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self._drag_region or self._drag_start is None or self._drag_start_rect is None:
            return
        canvas = self._canvas_rect()
        delta = event.position().toPoint() - self._drag_start
        window = self._layout.window_rect
        dx = round(delta.x() / max(1, canvas.width()) * window.width)
        dy = round(delta.y() / max(1, canvas.height()) * window.height)
        moved = _clamp_rect(
            Rect(
                self._drag_start_rect.left + dx,
                self._drag_start_rect.top + dy,
                self._drag_start_rect.right + dx,
                self._drag_start_rect.bottom + dy,
            ),
            window,
        )
        self.set_layout_regions(_replace_region(self._layout, self._drag_region, moved))

    def mouseReleaseEvent(self, _event: QMouseEvent) -> None:
        self._drag_region = None
        self._drag_start = None
        self._drag_start_rect = None
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def _canvas_rect(self) -> QRect:
        margin = 14
        bounds = self.rect().adjusted(margin, margin, -margin, -margin)
        source = self._screenshot.size() if self._screenshot and not self._screenshot.isNull() else None
        source_width = source.width() if source else self._layout.window_rect.width
        source_height = source.height() if source else self._layout.window_rect.height
        aspect = source_width / max(1, source_height)
        width = bounds.width()
        height = round(width / aspect)
        if height > bounds.height():
            height = bounds.height()
            width = round(height * aspect)
        left = bounds.left() + (bounds.width() - width) // 2
        top = bounds.top() + (bounds.height() - height) // 2
        return QRect(left, top, width, height)

    def _to_canvas_rect(self, rect: Rect, canvas: QRect) -> QRect:
        window = self._layout.window_rect
        left = canvas.left() + round((rect.left - window.left) / max(1, window.width) * canvas.width())
        top = canvas.top() + round((rect.top - window.top) / max(1, window.height) * canvas.height())
        right = canvas.left() + round((rect.right - window.left) / max(1, window.width) * canvas.width())
        bottom = canvas.top() + round((rect.bottom - window.top) / max(1, window.height) * canvas.height())
        return QRect(left, top, max(1, right - left), max(1, bottom - top))

    def _region_rects(self) -> dict[str, Rect]:
        return {
            "nav": self._layout.nav_rect,
            "chat_list": self._layout.chat_list_rect,
            "title": self._layout.title_rect,
            "message": self._layout.message_rect,
            "input": self._layout.input_rect,
        }

    def _paint_ocr_boxes(self, painter: QPainter, canvas: QRect) -> None:
        painter.setFont(QFont(painter.font().family(), 8, QFont.Weight.Bold))
        for box in self._ocr_result.boxes:
            screen_rect = self._to_canvas_rect(box.rect, canvas)
            painter.fillRect(screen_rect, QColor(255, 255, 255, 176))
            painter.setPen(QPen(QColor("#111827"), 1))
            painter.drawRect(screen_rect)
            painter.setPen(QColor("#111827"))
            text = f"{box.text} {box.confidence:.2f}"
            painter.drawText(
                screen_rect.adjusted(4, 2, -4, -2),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                text,
            )


def _replace_region(layout: LayoutRegions, key: str, rect: Rect) -> LayoutRegions:
    if key == "nav":
        return replace(layout, nav_rect=rect)
    if key == "chat_list":
        return replace(layout, chat_list_rect=rect)
    if key == "title":
        return replace(layout, title_rect=rect)
    if key == "message":
        return replace(layout, message_rect=rect)
    if key == "input":
        return replace(layout, input_rect=rect)
    return layout


def _clamp_rect(rect: Rect, window: Rect) -> Rect:
    width = max(20, min(rect.width, window.width))
    height = max(20, min(rect.height, window.height))
    left = max(window.left, min(rect.left, window.right - width))
    top = max(window.top, min(rect.top, window.bottom - height))
    return Rect(left, top, left + width, top + height)
