from __future__ import annotations

from abc import ABC, abstractmethod
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from typing import Any

from PIL import Image

from whochat.config import OcrConfig
from whochat.core.paths import app_data_dir
from whochat.core.runtime import LayoutRegions, Rect
from whochat.diagnostics import append_diagnostics_log, configure_native_runtime_limits
from whochat.ocr.models import OcrRegion, OcrResult, OcrTextBox


class OcrEngine(ABC):
    name: str

    @abstractmethod
    def recognize(self, image_path: Path, layout: LayoutRegions) -> OcrResult:
        raise NotImplementedError


class PreviewOcrEngine(OcrEngine):
    name = "preview-fixture"

    def recognize(self, image_path: Path, layout: LayoutRegions) -> OcrResult:
        if not image_path.exists():
            return OcrResult([], str(image_path), self.name, "截图不存在，无法生成 OCR 预览")
        with Image.open(image_path) as image:
            width, height = image.size
        if width < 40 or height < 40:
            return OcrResult([], str(image_path), self.name, "截图尺寸过小")

        boxes = [
            OcrTextBox("标题候选", _box_inside(layout.title_rect, 0.04, 0.25, 0.24, 0.68), 0.72, OcrRegion.TITLE, self.name),
            OcrTextBox("聊天列表候选", _box_inside(layout.chat_list_rect, 0.08, 0.06, 0.68, 0.13), 0.68, OcrRegion.CHAT_LIST, self.name),
            OcrTextBox("对方消息候选", _box_inside(layout.message_rect, 0.08, 0.12, 0.42, 0.22), 0.66, OcrRegion.MESSAGE, self.name),
            OcrTextBox("我的消息候选", _box_inside(layout.message_rect, 0.58, 0.28, 0.94, 0.38), 0.66, OcrRegion.MESSAGE, self.name),
            OcrTextBox("输入区候选", _box_inside(layout.input_rect, 0.06, 0.22, 0.38, 0.46), 0.61, OcrRegion.INPUT, self.name),
        ]
        return OcrResult(
            boxes=boxes,
            source_image=str(image_path),
            engine=self.name,
            warning="当前为校准预览引擎，不代表真实 OCR 结果",
        )


class RapidOcrEngine(OcrEngine):
    name = "rapidocr"

    def __init__(self, config: OcrConfig) -> None:
        self.config = config
        self._engine = None

    def recognize(self, image_path: Path, layout: LayoutRegions) -> OcrResult:
        if not image_path.exists():
            return OcrResult([], str(image_path), self.name, "截图不存在，无法执行 RapidOCR")
        try:
            engine = self._get_engine()
            raw = engine(str(image_path))
        except Exception as exc:
            return OcrResult([], str(image_path), self.name, f"RapidOCR 不可用：{exc}")
        boxes = _boxes_from_rapid_result(raw, self.config.min_confidence, self.name)
        return OcrResult(boxes, str(image_path), self.name, None if boxes else "RapidOCR 未返回文本")

    def _get_engine(self):
        if self._engine is None:
            from rapidocr import RapidOCR

            self._engine = RapidOCR()
        return self._engine


class PaddleOcrEngine(OcrEngine):
    name = "paddleocr"

    def __init__(self, config: OcrConfig) -> None:
        self.config = config
        self._engine = None
        self._failure_count = 0
        self._unavailable_until = 0.0
        self._daemon: subprocess.Popen | None = None
        self._daemon_stdout: queue.Queue[str] | None = None
        self._daemon_lock = threading.Lock()

    def recognize(self, image_path: Path, layout: LayoutRegions) -> OcrResult:
        if not image_path.exists():
            return OcrResult([], str(image_path), self.name, "截图不存在，无法执行 PaddleOCR")
        now = time.monotonic()
        if self._unavailable_until > now:
            remaining = int(self._unavailable_until - now)
            return OcrResult([], str(image_path), self.name, f"PaddleOCR 暂停中：连续失败后熔断，约 {remaining}s 后重试")
        worker_mode = os.environ.get("WHOCHAT_PADDLEOCR_WORKER_MODE", "daemon").strip().lower()
        if worker_mode == "daemon":
            return self._record_health(self._recognize_in_daemon(image_path))
        if os.environ.get("WHOCHAT_PADDLEOCR_SUBPROCESS", "1") != "0":
            return self._record_health(self._recognize_in_subprocess(image_path))
        try:
            engine = self._get_engine()
            raw = _run_paddle_ocr(engine, image_path)
        except Exception as exc:
            return self._record_health(OcrResult([], str(image_path), self.name, f"PaddleOCR 不可用：{exc}"))
        boxes = _boxes_from_paddle_result(raw, self.config.min_confidence, self.name)
        return self._record_health(OcrResult(boxes, str(image_path), self.name, None if boxes else "PaddleOCR 未返回文本"))

    def shutdown(self) -> None:
        self._stop_daemon()

    def _record_health(self, result: OcrResult) -> OcrResult:
        if result.warning and ("失败" in result.warning or "不可用" in result.warning or "超时" in result.warning or "不可解析" in result.warning):
            self._failure_count += 1
            append_diagnostics_log("ocr_worker", f"paddle_failure_count={self._failure_count} warning={result.warning}")
            if self._failure_count >= 2:
                cooldown = int(os.environ.get("WHOCHAT_PADDLEOCR_FAILURE_COOLDOWN_SECONDS", "180"))
                self._unavailable_until = time.monotonic() + cooldown
                append_diagnostics_log("ocr_worker", f"paddle_circuit_open cooldown={cooldown}s")
        else:
            if self._failure_count:
                append_diagnostics_log("ocr_worker", "paddle_recovered")
            self._failure_count = 0
            self._unavailable_until = 0.0
        return result

    def _recognize_in_subprocess(self, image_path: Path) -> OcrResult:
        timeout = int(os.environ.get("WHOCHAT_PADDLEOCR_TIMEOUT_SECONDS", "90"))
        command = [
            sys.executable,
            "-m",
            "whochat.ocr.paddle_worker",
            str(image_path),
            "--language",
            self.config.language,
            "--min-confidence",
            str(self.config.min_confidence),
            "--use-gpu",
            "1" if self.config.use_gpu else "0",
        ]
        env = {**os.environ, "PYTHONUTF8": "1"}
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                cwd=str(Path(__file__).resolve().parents[2]),
                env=env,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired:
            _log_paddle_worker(image_path, timeout * 1000, "timeout", f"timeout={timeout}s")
            return OcrResult([], str(image_path), self.name, f"PaddleOCR 超时：{timeout}s")
        except Exception as exc:
            _log_paddle_worker(image_path, _elapsed_ms(started), "spawn_failed", str(exc))
            return OcrResult([], str(image_path), self.name, f"PaddleOCR 子进程不可用：{exc}")
        elapsed_ms = _elapsed_ms(started)
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip().splitlines()[-4:]
            _log_paddle_worker(image_path, elapsed_ms, f"exit={completed.returncode}", " | ".join(detail))
            return OcrResult([], str(image_path), self.name, "PaddleOCR 子进程失败：" + " | ".join(detail))
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            detail = (completed.stdout or completed.stderr or "").strip().splitlines()[-4:]
            _log_paddle_worker(image_path, elapsed_ms, "bad_json", f"{exc}; {' | '.join(detail)}")
            return OcrResult([], str(image_path), self.name, f"PaddleOCR 输出不可解析：{exc}; {' | '.join(detail)}")
        boxes = [
            OcrTextBox(
                text=item["text"],
                rect=Rect(*item["rect"]),
                confidence=float(item["confidence"]),
                region=OcrRegion.UNKNOWN,
                source=self.name,
            )
            for item in payload.get("boxes", [])
        ]
        warning = payload.get("warning")
        stderr_tail = " | ".join((completed.stderr or "").strip().splitlines()[-3:])
        _log_paddle_worker(image_path, elapsed_ms, "ok", f"boxes={len(boxes)} warning={warning or '-'} stderr={stderr_tail or '-'}")
        return OcrResult(boxes, str(image_path), self.name, warning if warning else None)

    def _recognize_in_daemon(self, image_path: Path) -> OcrResult:
        timeout = int(os.environ.get("WHOCHAT_PADDLEOCR_TIMEOUT_SECONDS", "90"))
        started = time.monotonic()
        with self._daemon_lock:
            try:
                daemon = self._ensure_daemon(timeout)
                assert self._daemon_stdout is not None
                daemon.stdin.write(json.dumps({"image_path": str(image_path)}, ensure_ascii=False) + "\n")
                daemon.stdin.flush()
                line = self._daemon_stdout.get(timeout=timeout)
            except queue.Empty:
                self._stop_daemon()
                _log_paddle_worker(image_path, timeout * 1000, "daemon_timeout", f"timeout={timeout}s")
                return OcrResult([], str(image_path), self.name, f"PaddleOCR daemon 超时：{timeout}s")
            except Exception as exc:
                self._stop_daemon()
                _log_paddle_worker(image_path, _elapsed_ms(started), "daemon_failed", str(exc))
                return OcrResult([], str(image_path), self.name, f"PaddleOCR daemon 不可用：{exc}")
        elapsed_ms = _elapsed_ms(started)
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            self._stop_daemon()
            _log_paddle_worker(image_path, elapsed_ms, "daemon_bad_json", f"{exc}; {line[:500]}")
            return OcrResult([], str(image_path), self.name, f"PaddleOCR daemon 输出不可解析：{exc}")
        if payload.get("status") != "ok":
            error = str(payload.get("error") or payload.get("warning") or payload.get("status") or "unknown")
            _log_paddle_worker(image_path, elapsed_ms, "daemon_error", error)
            return OcrResult([], str(image_path), self.name, f"PaddleOCR daemon 失败：{error}")
        boxes = [
            OcrTextBox(
                text=item["text"],
                rect=Rect(*item["rect"]),
                confidence=float(item["confidence"]),
                region=OcrRegion.UNKNOWN,
                source=self.name,
            )
            for item in payload.get("boxes", [])
        ]
        warning = payload.get("warning")
        _log_paddle_worker(image_path, elapsed_ms, "daemon_ok", f"boxes={len(boxes)} warning={warning or '-'}")
        return OcrResult(boxes, str(image_path), self.name, warning if warning else None)

    def _ensure_daemon(self, timeout: int) -> subprocess.Popen:
        if self._daemon is not None and self._daemon.poll() is None and self._daemon_stdout is not None:
            return self._daemon
        self._stop_daemon()
        command = [
            sys.executable,
            "-m",
            "whochat.ocr.paddle_daemon",
            "--language",
            self.config.language,
            "--min-confidence",
            str(self.config.min_confidence),
            "--use-gpu",
            "1" if self.config.use_gpu else "0",
        ]
        env = {**os.environ, "PYTHONUTF8": "1"}
        self._daemon = subprocess.Popen(
            command,
            cwd=str(Path(__file__).resolve().parents[2]),
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._daemon_stdout = queue.Queue()
        assert self._daemon.stdout is not None
        threading.Thread(target=_read_daemon_stdout, args=(self._daemon.stdout, self._daemon_stdout), daemon=True).start()
        if self._daemon.stderr is not None:
            threading.Thread(target=_drain_daemon_stderr, args=(self._daemon.stderr,), daemon=True).start()
        try:
            line = self._daemon_stdout.get(timeout=timeout)
        except queue.Empty as exc:
            self._stop_daemon()
            raise TimeoutError(f"daemon startup timed out after {timeout}s") from exc
        payload = json.loads(line)
        if payload.get("status") != "ready":
            self._stop_daemon()
            raise RuntimeError(f"daemon startup failed: {payload}")
        return self._daemon

    def _stop_daemon(self) -> None:
        daemon = self._daemon
        self._daemon = None
        self._daemon_stdout = None
        if daemon is None:
            return
        try:
            if daemon.poll() is None:
                daemon.kill()
        except Exception:
            return

    def _get_engine(self):
        if self._engine is None:
            _configure_paddle_cache()
            from paddleocr import PaddleOCR

            attempts = [
                {
                    "device": "gpu" if self.config.use_gpu else "cpu",
                    "enable_mkldnn": False,
                    "text_detection_model_name": "PP-OCRv5_mobile_det",
                    "text_recognition_model_name": "PP-OCRv5_mobile_rec",
                    "use_doc_orientation_classify": False,
                    "use_doc_unwarping": False,
                    "use_textline_orientation": False,
                    "cpu_threads": 1,
                },
                {"lang": self.config.language, "use_angle_cls": False},
                {"lang": self.config.language},
            ]
            last_error: Exception | None = None
            for kwargs in attempts:
                try:
                    self._engine = PaddleOCR(**kwargs)
                    break
                except Exception as exc:
                    last_error = exc
            if self._engine is None and last_error is not None:
                raise last_error
        return self._engine


def create_ocr_engine(config: OcrConfig | None = None) -> OcrEngine:
    config = config or OcrConfig()
    if config.provider == "RapidOCR":
        return RapidOcrEngine(config)
    if config.provider == "PaddleOCR":
        return PaddleOcrEngine(config)
    return PreviewOcrEngine()


def _configure_paddle_cache() -> None:
    configure_native_runtime_limits()
    cache_home = app_data_dir() / "ocr_cache" / "home"
    paddle_home = cache_home / ".cache" / "paddle"
    paddleocr_home = cache_home / ".cache" / "paddleocr"
    paddle_home.mkdir(parents=True, exist_ok=True)
    paddleocr_home.mkdir(parents=True, exist_ok=True)
    # PaddlePaddle still uses expanduser("~/.cache/paddle") in some import paths.
    os.environ["USERPROFILE"] = str(cache_home)
    os.environ["PADDLE_HOME"] = str(paddle_home)
    os.environ["PADDLEOCR_HOME"] = str(paddleocr_home)
    os.environ["XDG_CACHE_HOME"] = str(cache_home / ".cache")
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _log_paddle_worker(image_path: Path, elapsed_ms: int, status: str, detail: str) -> None:
    clipped = " ".join(detail.split())[:1000]
    append_diagnostics_log("ocr_worker", f"image={image_path.name} elapsed_ms={elapsed_ms} status={status} {clipped}")


def _read_daemon_stdout(stream, output: queue.Queue[str]) -> None:
    for line in stream:
        cleaned = line.strip()
        if cleaned:
            output.put(cleaned)


def _drain_daemon_stderr(stream) -> None:
    for line in stream:
        cleaned = line.strip()
        if cleaned:
            append_diagnostics_log("ocr_worker", f"paddle_daemon_stderr {cleaned[:1000]}")


def _box_inside(rect: Rect, left: float, top: float, right: float, bottom: float) -> Rect:
    return Rect(
        rect.left + round(rect.width * left),
        rect.top + round(rect.height * top),
        rect.left + round(rect.width * right),
        rect.top + round(rect.height * bottom),
    )


def _boxes_from_rapid_result(raw: Any, min_confidence: float, source: str) -> list[OcrTextBox]:
    items = getattr(raw, "boxes", None)
    texts = getattr(raw, "txts", None) or getattr(raw, "texts", None)
    scores = getattr(raw, "scores", None)
    if items is not None and texts is not None and scores is not None:
        return _boxes_from_parts(items, texts, scores, min_confidence, source)
    if isinstance(raw, tuple) and len(raw) >= 3:
        return _boxes_from_parts(raw[0], raw[1], raw[2], min_confidence, source)
    if isinstance(raw, list):
        return _boxes_from_records(raw, min_confidence, source)
    return []


def _boxes_from_paddle_result(raw: Any, min_confidence: float, source: str) -> list[OcrTextBox]:
    if isinstance(raw, list) and len(raw) == 1 and isinstance(raw[0], list):
        raw = raw[0]
    if isinstance(raw, list) and raw and all(isinstance(item, dict) for item in raw):
        result: list[OcrTextBox] = []
        for page in raw:
            texts = page.get("rec_texts")
            scores = page.get("rec_scores")
            boxes = page.get("rec_polys") or page.get("dt_polys") or page.get("rec_boxes")
            if texts is not None and scores is not None and boxes is not None:
                result.extend(_boxes_from_parts(boxes, texts, scores, min_confidence, source))
            else:
                parsed = _parse_ocr_record(page)
                if parsed is not None:
                    points, text, confidence = parsed
                    if confidence >= min_confidence and text.strip():
                        result.append(OcrTextBox(text.strip(), _rect_from_points(points), confidence, OcrRegion.UNKNOWN, source))
        return result
    if isinstance(raw, list):
        return _boxes_from_records(raw, min_confidence, source)
    return []


def _boxes_from_parts(boxes: Any, texts: Any, scores: Any, min_confidence: float, source: str) -> list[OcrTextBox]:
    result: list[OcrTextBox] = []
    for box, text, score in zip(_items(boxes), _items(texts), _items(scores)):
        confidence = _float(score)
        if confidence < min_confidence:
            continue
        value = str(text).strip()
        if not value:
            continue
        result.append(OcrTextBox(value, _rect_from_points(box), confidence, OcrRegion.UNKNOWN, source))
    return result


def _boxes_from_records(records: Any, min_confidence: float, source: str) -> list[OcrTextBox]:
    result: list[OcrTextBox] = []
    for record in _items(records):
        parsed = _parse_ocr_record(record)
        if parsed is None:
            continue
        points, text, confidence = parsed
        if confidence < min_confidence or not text.strip():
            continue
        result.append(OcrTextBox(text.strip(), _rect_from_points(points), confidence, OcrRegion.UNKNOWN, source))
    return result


def _parse_ocr_record(record: Any) -> tuple[Any, str, float] | None:
    if isinstance(record, dict):
        points = record.get("box") or record.get("points") or record.get("dt_polys")
        text = record.get("text") or record.get("rec_text") or record.get("label")
        score = record.get("score") or record.get("confidence") or record.get("rec_score")
        if points is not None and text is not None and score is not None:
            return points, str(text), _float(score)
    if isinstance(record, (list, tuple)) and len(record) >= 2:
        points = record[0]
        payload = record[1]
        if isinstance(payload, (list, tuple)) and len(payload) >= 2:
            return points, str(payload[0]), _float(payload[1])
        if len(record) >= 3:
            return points, str(record[1]), _float(record[2])
    return None


def _run_paddle_ocr(engine: Any, image_path: Path) -> Any:
    if hasattr(engine, "ocr"):
        return engine.ocr(str(image_path))
    if hasattr(engine, "predict"):
        return engine.predict(str(image_path))
    raise RuntimeError("PaddleOCR engine has neither ocr() nor predict()")


def _rect_from_points(points: Any) -> Rect:
    normalized = []
    for point in [] if points is None else points:
        if hasattr(point, "__len__") and len(point) >= 2:
            normalized.append((int(round(float(point[0]))), int(round(float(point[1])))))
    if not normalized:
        return Rect(0, 0, 0, 0)
    xs = [point[0] for point in normalized]
    ys = [point[1] for point in normalized]
    return Rect(min(xs), min(ys), max(xs), max(ys))


def _items(value: Any) -> Any:
    if value is None:
        return []
    return value


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
