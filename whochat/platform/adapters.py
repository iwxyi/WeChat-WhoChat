from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from whochat.core.runtime import (
    LayoutRegions,
    PageClassification,
    PageType,
    Rect,
    RegionSource,
    TargetApp,
    WindowSnapshot,
    WindowState,
    layout_from_calibration,
)
from whochat.platform.window_tracker import WindowInfo
from whochat.ocr.models import OcrResult
from whochat.ocr.parser import classify_page_from_ocr


class PlatformAdapter(ABC):
    target: TargetApp

    @abstractmethod
    def window_snapshot(self, window: WindowInfo | None) -> WindowSnapshot:
        raise NotImplementedError

    @abstractmethod
    def estimate_layout(self, window: WindowSnapshot) -> LayoutRegions | None:
        raise NotImplementedError

    @abstractmethod
    def classify_page(self, window: WindowSnapshot, layout: LayoutRegions | None) -> PageClassification:
        raise NotImplementedError


class WeChatAdapter(PlatformAdapter):
    target = TargetApp.WECHAT

    def __init__(self, calibrations=None) -> None:
        self.calibrations = calibrations

    def window_snapshot(self, window: WindowInfo | None) -> WindowSnapshot:
        if window is None:
            return WindowSnapshot(
                target=self._target_from_window(window),
                hwnd=None,
                title="",
                process_name="",
                rect=None,
                state=WindowState.MISSING,
                app_label="微信",
                diagnostic="未发现已启用的目标聊天窗口",
            )
        rect = Rect.from_tuple(window.rect)
        if window.minimized:
            state = WindowState.MINIMIZED
        elif not window.foreground:
            state = WindowState.UNAVAILABLE
        elif not window.visible:
            state = WindowState.UNAVAILABLE
        else:
            state = WindowState.VISIBLE if rect.width > 120 and rect.height > 120 else WindowState.MINIMIZED
        return WindowSnapshot(
            target=self._target_from_window(window),
            hwnd=window.hwnd,
            title=window.title,
            process_name=window.process_name,
            rect=rect,
            state=state,
            app_label=window.app_label or ("微信" if self._target_from_window(window) == TargetApp.WECHAT else "通用聊天"),
            diagnostic=window.diagnostic,
            foreground=window.foreground,
            bubble_profile=window.bubble_profile,
        )

    def estimate_layout(self, window: WindowSnapshot) -> LayoutRegions | None:
        if window.rect is None or window.state != WindowState.VISIBLE:
            return None
        rect = window.rect
        width = rect.width
        height = rect.height
        if width < 520 or height < 420:
            return None

        calibration_target = TargetApp.WECHAT if window.target == TargetApp.WECHAT else TargetApp.GENERIC_CHAT
        calibration = self.calibrations.get_active(calibration_target) if self.calibrations else None
        if calibration:
            layout = layout_from_calibration(calibration, rect)
            return LayoutRegions(
                target_app=layout.target_app,
                bubble_profile=window.bubble_profile if window.bubble_profile != "auto" else layout.bubble_profile,
                window_rect=layout.window_rect,
                nav_rect=layout.nav_rect,
                chat_list_rect=layout.chat_list_rect,
                content_rect=layout.content_rect,
                title_rect=layout.title_rect,
                message_rect=layout.message_rect,
                input_rect=layout.input_rect,
                confidence=layout.confidence,
                source=layout.source,
                reason=layout.reason,
            )

        profile = _wechat_layout_profile(width, height) if window.target == TargetApp.WECHAT else _generic_layout_profile(width, height)
        nav_width = _clamp(round(width * profile.nav_ratio), profile.nav_min, profile.nav_max)
        chat_list_width = _clamp(round(width * profile.chat_list_ratio), profile.chat_list_min, profile.chat_list_max)
        title_height = _clamp(round(height * profile.title_ratio), profile.title_min, profile.title_max)
        input_height = _clamp(round(height * profile.input_ratio), profile.input_min, profile.input_max)

        min_content_width = 280
        max_sidebar_width = max(0, width - min_content_width)
        if nav_width + chat_list_width > max_sidebar_width:
            overflow = nav_width + chat_list_width - max_sidebar_width
            chat_list_width = max(profile.chat_list_min, chat_list_width - overflow)
        if nav_width + chat_list_width > max_sidebar_width:
            nav_width = max(profile.nav_min, max_sidebar_width - chat_list_width)

        nav = Rect(rect.left, rect.top, rect.left + nav_width, rect.bottom)
        chat_list = Rect(nav.right, rect.top, nav.right + chat_list_width, rect.bottom)
        content = Rect(chat_list.right, rect.top, rect.right, rect.bottom)
        title = Rect(content.left, content.top, content.right, content.top + title_height)
        input_rect = Rect(content.left, rect.bottom - input_height, content.right, rect.bottom)
        message = Rect(content.left, title.bottom, content.right, input_rect.top)
        confidence = profile.confidence
        platform_label = "微信 PC" if window.target == TargetApp.WECHAT else "通用聊天"
        reason = f"基于{platform_label} {profile.name} 布局 profile 的几何先验；优先使用相对比例并保留内容区最小宽度"
        return LayoutRegions(
            target_app=window.target,
            bubble_profile=window.bubble_profile,
            window_rect=rect,
            nav_rect=nav,
            chat_list_rect=chat_list,
            content_rect=content,
            title_rect=title,
            message_rect=message,
            input_rect=input_rect,
            confidence=confidence,
            source=RegionSource.AUTO,
            reason=reason,
        )

    def _target_from_window(self, window: WindowInfo | None) -> TargetApp:
        if window is None:
            return self.target
        if window.target_app == TargetApp.WECHAT.value:
            return TargetApp.WECHAT
        if window.target_app == TargetApp.GENERIC_CHAT.value:
            return TargetApp.GENERIC_CHAT
        return TargetApp.GENERIC_CHAT

    def classify_page(self, window: WindowSnapshot, layout: LayoutRegions | None) -> PageClassification:
        if window.state != WindowState.VISIBLE:
            reason = window.diagnostic or "窗口不可见、最小化或尺寸不可用"
            return PageClassification(PageType.UNKNOWN, 0.0, reason)
        if layout is None:
            return PageClassification(PageType.UNKNOWN, 0.15, "窗口尺寸不足或无法估算区域")
        if window.title in {"微信", "WeChat"}:
            return PageClassification(
                PageType.UNKNOWN,
                0.45,
                "微信窗口已命中，等待 OCR 采集确认聊天页",
            )
        return PageClassification(
            PageType.UNKNOWN,
            0.35,
            "页面分类尚未接入 OCR 和视觉特征，默认阻止 AI 请求",
        )

    def classify_page_with_ocr(
        self,
        window: WindowSnapshot,
        layout: LayoutRegions | None,
        ocr_result: OcrResult | None,
    ) -> PageClassification:
        base = self.classify_page(window, layout)
        if layout is None or ocr_result is None or window.state != WindowState.VISIBLE:
            return base
        ocr_page = classify_page_from_ocr(ocr_result, layout)
        if ocr_page.confidence > base.confidence:
            return ocr_page
        return base


def _clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(value, upper))


@dataclass(frozen=True)
class _LayoutProfile:
    name: str
    nav_ratio: float
    nav_min: int
    nav_max: int
    chat_list_ratio: float
    chat_list_min: int
    chat_list_max: int
    title_ratio: float
    title_min: int
    title_max: int
    input_ratio: float
    input_min: int
    input_max: int
    confidence: float


def _wechat_layout_profile(width: int, height: int) -> _LayoutProfile:
    aspect = width / max(1, height)
    if width < 760 or aspect < 1.25:
        return _LayoutProfile(
            name="compact",
            nav_ratio=0.09,
            nav_min=44,
            nav_max=64,
            chat_list_ratio=0.31,
            chat_list_min=170,
            chat_list_max=250,
            title_ratio=0.095,
            title_min=44,
            title_max=66,
            input_ratio=0.24,
            input_min=96,
            input_max=150,
            confidence=0.5,
        )
    if width >= 1500 or aspect >= 2.05:
        return _LayoutProfile(
            name="wide",
            nav_ratio=0.055,
            nav_min=56,
            nav_max=82,
            chat_list_ratio=0.22,
            chat_list_min=260,
            chat_list_max=380,
            title_ratio=0.075,
            title_min=50,
            title_max=76,
            input_ratio=0.20,
            input_min=120,
            input_max=190,
            confidence=0.56,
        )
    return _LayoutProfile(
        name="standard",
        nav_ratio=0.075,
        nav_min=48,
        nav_max=76,
        chat_list_ratio=0.275,
        chat_list_min=210,
        chat_list_max=330,
        title_ratio=0.085,
        title_min=48,
        title_max=72,
        input_ratio=0.22,
        input_min=116,
        input_max=170,
        confidence=0.58,
    )


def _generic_layout_profile(width: int, height: int) -> _LayoutProfile:
    if width < 820:
        return _LayoutProfile(
            name="compact",
            nav_ratio=0.0,
            nav_min=0,
            nav_max=0,
            chat_list_ratio=0.34,
            chat_list_min=190,
            chat_list_max=280,
            title_ratio=0.09,
            title_min=48,
            title_max=74,
            input_ratio=0.22,
            input_min=100,
            input_max=165,
            confidence=0.38,
        )
    return _LayoutProfile(
        name="standard",
        nav_ratio=0.0,
        nav_min=0,
        nav_max=0,
        chat_list_ratio=0.30,
        chat_list_min=240,
        chat_list_max=380,
        title_ratio=0.085,
        title_min=52,
        title_max=78,
        input_ratio=0.20,
        input_min=112,
        input_max=180,
        confidence=0.42,
    )
