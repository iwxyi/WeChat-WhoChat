from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from whochat.core.runtime import CaptureDecision, CapturePolicy, RuntimeState, WindowState


@dataclass
class CaptureGate:
    policy: CapturePolicy
    last_capture_ms: int = 0
    last_hash: str | None = None
    last_rect: tuple[int, int, int, int] | None = None

    def evaluate(self, state: RuntimeState, image_path: Path | None = None) -> CaptureDecision:
        if state.paused:
            return CaptureDecision(False, "用户已暂停采集")
        if state.window.state != WindowState.VISIBLE:
            return CaptureDecision(False, f"窗口状态不可采集：{state.window.state.value}")
        if state.layout is None:
            return CaptureDecision(False, "区域未识别，跳过截图")
        if state.layout.confidence < 0.5:
            return CaptureDecision(False, "区域置信度过低，等待校准")

        now_ms = int(time.monotonic() * 1000)
        elapsed = now_ms - self.last_capture_ms if self.last_capture_ms else None
        if elapsed is not None and elapsed < self.policy.screenshot_min_interval_ms:
            return CaptureDecision(False, "截图节流中", elapsed_ms=elapsed)

        rect = state.layout.message_rect.as_tuple()
        if self.last_rect and self.last_rect != rect and elapsed is not None and elapsed < self.policy.window_stable_delay_ms:
            return CaptureDecision(False, "窗口区域刚变化，等待稳定", elapsed_ms=elapsed)

        snapshot_hash = image_hash(image_path) if image_path else None
        if snapshot_hash and self.last_hash:
            distance = hash_distance(snapshot_hash, self.last_hash)
            if distance < self.policy.min_hash_distance:
                return CaptureDecision(False, "截图内容变化很小，跳过 OCR", snapshot_hash=snapshot_hash, elapsed_ms=elapsed)

        self.last_capture_ms = now_ms
        self.last_rect = rect
        if snapshot_hash:
            self.last_hash = snapshot_hash
        return CaptureDecision(True, "允许采集", snapshot_hash=snapshot_hash, elapsed_ms=elapsed)


def image_hash(path: Path, size: int = 8) -> str:
    with Image.open(path) as image:
        grayscale = image.convert("L").resize((size, size))
        pixels = list(grayscale.getdata())
    average = sum(pixels) / len(pixels)
    bits = ["1" if pixel >= average else "0" for pixel in pixels]
    value = int("".join(bits), 2)
    return f"{value:0{size * size // 4}x}"


def hash_distance(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


