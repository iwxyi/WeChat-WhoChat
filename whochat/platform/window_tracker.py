from __future__ import annotations

from dataclasses import dataclass

from whochat.config import TargetWindowConfig, default_target_windows


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    process_name: str
    rect: tuple[int, int, int, int]
    visible: bool
    target_app: str = "wechat"
    app_label: str = "微信"
    process_id: int | None = None
    minimized: bool = False
    diagnostic: str = ""
    foreground: bool = True


@dataclass(frozen=True)
class WindowMatchDiagnostic:
    hwnd: int
    title: str
    process_name: str
    process_id: int | None
    matched: bool
    target_app: str
    app_label: str
    reason: str
    foreground: bool = False


def find_wechat_windows() -> list[WindowInfo]:
    targets = [target for target in default_target_windows() if target.app_id == "wechat"]
    return find_target_windows(targets)


def find_target_windows(targets: list[TargetWindowConfig]) -> list[WindowInfo]:
    try:
        import win32gui
        import win32process
    except ImportError:
        return []

    windows: list[WindowInfo] = []
    enabled_targets = [target for target in targets if target.enabled]
    process_ids = _process_ids_by_names(_target_process_names(enabled_targets))
    foreground_hwnd = foreground_window_handle()

    def enum_handler(hwnd: int, _extra) -> None:
        try:
            visible = bool(win32gui.IsWindowVisible(hwnd))
            if not visible:
                return
            title = win32gui.GetWindowText(hwnd).strip()
            if not title:
                return
            _thread_id, process_id = win32process.GetWindowThreadProcessId(hwnd)
            process_name = process_ids.get(process_id, "") or _process_name_by_pid(process_id)
            target = _match_target(enabled_targets, title, process_name)
            if target is None:
                return
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            minimized = bool(win32gui.IsIconic(hwnd))
            foreground = foreground_hwnd is None or hwnd == foreground_hwnd
            windows.append(
                WindowInfo(
                    hwnd=hwnd,
                    title=title,
                    process_name=process_name,
                    rect=(left, top, right, bottom),
                    visible=visible and not minimized and foreground,
                    target_app=target.app_id,
                    app_label=target.label,
                    process_id=process_id,
                    minimized=minimized,
                    diagnostic=_window_diagnostic(title, process_name, minimized, foreground),
                    foreground=foreground,
                )
            )
        except Exception:
            return

    try:
        win32gui.EnumWindows(enum_handler, None)
    except Exception:
        return windows
    return windows


def diagnose_target_windows(targets: list[TargetWindowConfig], limit: int = 30) -> list[WindowMatchDiagnostic]:
    try:
        import win32gui
        import win32process
    except ImportError:
        return []

    enabled_targets = [target for target in targets if target.enabled]
    process_ids = _process_ids_by_names(_target_process_names(enabled_targets))
    diagnostics: list[WindowMatchDiagnostic] = []
    foreground_hwnd = foreground_window_handle()

    def enum_handler(hwnd: int, _extra) -> None:
        if len(diagnostics) >= limit:
            return
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd).strip()
            if not title:
                return
            _thread_id, process_id = win32process.GetWindowThreadProcessId(hwnd)
            process_name = process_ids.get(process_id, "") or _process_name_by_pid(process_id)
            target = _match_target(enabled_targets, title, process_name)
            raw_target = _match_target_raw(enabled_targets, title, process_name)
            related = target is not None or raw_target is not None or _looks_related_to_targets(title, process_name, enabled_targets)
            if not related:
                return
            diagnostics.append(
                WindowMatchDiagnostic(
                    hwnd=hwnd,
                    title=title,
                    process_name=process_name,
                    process_id=process_id,
                    matched=target is not None,
                    target_app=target.app_id if target else raw_target.app_id if raw_target else "",
                    app_label=target.label if target else raw_target.label if raw_target else "",
                    reason=_match_reason(title, process_name, target, raw_target),
                    foreground=foreground_hwnd is not None and hwnd == foreground_hwnd,
                )
            )
        except Exception:
            return

    try:
        win32gui.EnumWindows(enum_handler, None)
    except Exception:
        return diagnostics
    return diagnostics


def foreground_window_handle() -> int | None:
    try:
        import win32gui
    except ImportError:
        return None
    try:
        hwnd = win32gui.GetForegroundWindow()
    except Exception:
        return None
    return int(hwnd) if hwnd else None


def _target_process_names(targets: list[TargetWindowConfig]) -> set[str]:
    names: set[str] = set()
    for target in targets:
        names.update(_normalize_process_name(name) for name in target.process_names if name.strip())
    return names


def _match_target(targets: list[TargetWindowConfig], title: str, process_name: str) -> TargetWindowConfig | None:
    target = _match_target_raw(targets, title, process_name)
    if target is None:
        return None
    if _title_is_excluded(title, target):
        return None
    return target


def _match_target_raw(targets: list[TargetWindowConfig], title: str, process_name: str) -> TargetWindowConfig | None:
    normalized_process = _normalize_process_name(process_name)
    for target in targets:
        process_names = {_normalize_process_name(name) for name in target.process_names}
        if normalized_process and normalized_process in process_names:
            return target
        for keyword in target.title_keywords:
            value = keyword.strip()
            if value and _title_keyword_matches(title, value):
                return target
    return None


def _title_is_excluded(title: str, target: TargetWindowConfig) -> bool:
    normalized_title = " ".join(title.strip().split()).lower()
    if not normalized_title:
        return False
    for keyword in target.exclude_title_keywords:
        normalized_keyword = " ".join(keyword.strip().split()).lower()
        if normalized_keyword and normalized_keyword in normalized_title:
            return True
    return False


def _title_keyword_matches(title: str, keyword: str) -> bool:
    normalized_title = " ".join(title.strip().split()).lower()
    normalized_keyword = " ".join(keyword.strip().split()).lower()
    if not normalized_title or not normalized_keyword:
        return False
    if normalized_keyword in {"wechat", "微信"}:
        return normalized_title in {normalized_keyword, f"[{normalized_keyword}]", f"【{normalized_keyword}】"}
    return normalized_keyword in normalized_title


def _process_ids_by_names(names: set[str]) -> dict[int, str]:
    try:
        import win32process
    except ImportError:
        return {}

    result: dict[int, str] = {}
    try:
        import subprocess

        output = subprocess.check_output(
            ["tasklist", "/fo", "csv", "/nh"],
            text=True,
            encoding="mbcs",
            errors="ignore",
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        return result

    for line in output.splitlines():
        parts = [part.strip().strip('"') for part in line.split('","')]
        if len(parts) < 2:
            continue
        name = parts[0].strip('"')
        normalized = _normalize_process_name(name)
        if normalized not in names:
            continue
        try:
            result[int(parts[1].strip('"'))] = name
        except ValueError:
            continue
    return result


def _process_name_by_pid(pid: int) -> str:
    try:
        import psutil

        return str(psutil.Process(pid).name())
    except Exception:
        return ""


def _looks_related_to_targets(title: str, process_name: str, targets: list[TargetWindowConfig]) -> bool:
    haystack = f"{title} {process_name}".lower()
    for target in targets:
        for value in [*target.title_keywords, *target.process_names, target.label, target.app_id]:
            marker = value.strip().lower()
            if marker and marker.removesuffix(".exe") in haystack:
                return True
    return False


def _match_reason(
    title: str,
    process_name: str,
    target: TargetWindowConfig | None,
    raw_target: TargetWindowConfig | None = None,
) -> str:
    if target is None:
        if raw_target is not None and _title_is_excluded(title, raw_target):
            return "excluded_by_title"
        return "related_but_not_matched"
    normalized_process = _normalize_process_name(process_name)
    process_names = {_normalize_process_name(name) for name in target.process_names}
    if normalized_process and normalized_process in process_names:
        return "matched_by_process"
    return "matched_by_title"


def _normalize_process_name(value: str) -> str:
    cleaned = value.strip().lower()
    if not cleaned:
        return ""
    if not cleaned.endswith(".exe"):
        cleaned += ".exe"
    return cleaned


def _window_diagnostic(title: str, process_name: str, minimized: bool, foreground: bool) -> str:
    if minimized:
        return "目标窗口已最小化，悬浮窗和采集会暂停"
    if not foreground:
        return "目标窗口不是当前前景窗口；屏幕截图会被上层窗口遮挡，已暂停采集"
    if not process_name:
        return "仅通过窗口标题匹配，未读取到目标进程名；若采集失败，请检查权限或补充进程名规则"
    return ""
