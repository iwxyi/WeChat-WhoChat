from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

from whochat.ai.models import AIConnectionTestResult, ReplyContext, ReplyGenerationResult, ReplySuggestion
from whochat.ai.prompt import build_prompt_preview
from whochat.config import AppConfig
from whochat.core.models import ContactStatus, Speaker
from whochat.core.runtime import PageType
from whochat.diagnostics import append_diagnostics_log


class ReplyGenerator:
    def generate(self, context: ReplyContext, config: AppConfig) -> ReplyGenerationResult:
        blocked = _blocking_reason(context, config)
        if blocked:
            return ReplyGenerationResult(False, blocked, [], config.ai.provider)

        if config.ai.provider in {"OpenAI", "OpenAI Compatible"} and config.ai.api_key:
            return _generate_openai_compatible(context, config)

        return _generate_local_preview(context, config)


def test_ai_connection(config: AppConfig) -> AIConnectionTestResult:
    provider = config.ai.provider
    if provider == "Disabled":
        return AIConnectionTestResult(True, "disabled", provider, "AI 已禁用；不会发起网络请求")
    if provider not in {"OpenAI", "OpenAI Compatible"}:
        return AIConnectionTestResult(True, "local_preview", provider, "本地预览模式可用；不会发起网络请求")
    if not config.ai.api_key:
        return AIConnectionTestResult(False, "missing_api_key", provider, "缺少 API Key")
    if not config.ai.model.strip():
        return AIConnectionTestResult(False, "missing_model", provider, "缺少模型名称")
    if not config.ai.base_url.startswith(("http://", "https://")):
        return AIConnectionTestResult(False, "invalid_base_url", provider, "Base URL 需要以 http:// 或 https:// 开头")

    endpoint = _chat_completions_endpoint(config.ai.base_url)
    payload = {
        "model": config.ai.model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": "You are a connection test endpoint. Return compact json."},
            {"role": "user", "content": "Return json: {\"ok\":true}."},
        ],
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=_provider_headers(config.ai.api_key),
        method="POST",
    )
    timeout = max(3, min(config.ai.timeout_seconds, 20))
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw_body = response.read().decode("utf-8")
            elapsed = _elapsed_ms(started)
            _log_ai_provider(endpoint, elapsed, "connection_test_ok", f"status={getattr(response, 'status', '-')}")
            data = json.loads(raw_body)
    except urllib.error.HTTPError as exc:
        elapsed = _elapsed_ms(started)
        body = _read_http_error_body(exc)
        _log_ai_provider(endpoint, elapsed, f"connection_test_http_error:{exc.code}", f"reason={exc.reason} body={_clip(body, 500)}")
        return AIConnectionTestResult(
            False,
            f"http_error:{exc.code}",
            provider,
            _http_error_message(exc.code, exc.reason, body),
            elapsed,
        )
    except (urllib.error.URLError, TimeoutError) as exc:
        elapsed = _elapsed_ms(started)
        _log_ai_provider(endpoint, elapsed, "connection_test_transport_error", str(exc))
        return AIConnectionTestResult(False, "transport_error", provider, str(exc), elapsed)
    except json.JSONDecodeError as exc:
        elapsed = _elapsed_ms(started)
        _log_ai_provider(endpoint, elapsed, "connection_test_bad_json", str(exc))
        return AIConnectionTestResult(False, "bad_response_json", provider, f"返回不是合法 JSON：{exc}", elapsed)

    choices = data.get("choices") if isinstance(data, dict) else None
    if not isinstance(choices, list) or not choices:
        elapsed = _elapsed_ms(started)
        _log_ai_provider(endpoint, elapsed, "connection_test_bad_shape", _clip(str(data), 160))
        return AIConnectionTestResult(False, "bad_response_shape", provider, "返回结构缺少 choices", elapsed)
    return AIConnectionTestResult(True, "ok", provider, "连接测试通过", _elapsed_ms(started))


def _blocking_reason(context: ReplyContext, config: AppConfig) -> str | None:
    if config.ai.provider == "Disabled":
        return "AI 已在设置中禁用"
    if config.privacy.manual_protection_blocks_replies and context.strategy and context.strategy.requires_manual_reply:
        return "当前分组启用了手动回复保护"
    if config.capture.pause_ai_on_unknown_page and context.runtime.page.page_type not in {PageType.CHAT_DM, PageType.CHAT_GROUP}:
        return f"当前页面未确认是聊天页：{context.runtime.page.page_type.value}"
    if context.contact is None:
        return "聊天对象尚未识别或选择，不能生成回复建议"
    if context.contact.status == ContactStatus.IGNORED:
        return "聊天对象已被忽略，不能生成回复建议"
    if context.contact.status == ContactStatus.MERGED or context.contact.merged_into:
        return "聊天对象已合并到其他对象，请切换到合并后的对象"
    if _uses_cloud_provider(config) and not context.contact.allow_cloud_ai:
        return "联系人未允许发送上下文到第三方 AI"
    return None


def _uses_cloud_provider(config: AppConfig) -> bool:
    return config.ai.provider in {"OpenAI", "OpenAI Compatible"} and bool(config.ai.api_key)


def _generate_local_preview(context: ReplyContext, config: AppConfig) -> ReplyGenerationResult:
    strategy = context.strategy
    variants = _variants(strategy.reply_variants if strategy else "")
    recent_other = next((m.text for m in context.messages if m.speaker == Speaker.OTHER and m.text.strip()), "")
    goal = strategy.goal if strategy else "根据上下文给出自然、稳妥的回复建议"
    tone = strategy.tone if strategy else "自然、清晰"
    base = recent_other or "我看到了你的消息"
    suggestions = [
        ReplySuggestion(
            variants[0],
            f"收到，我先确认一下关键信息，稍后给你明确回复。",
            "low",
            f"目标：{goal}；语气：{tone}；适合先稳住上下文。",
        ),
        ReplySuggestion(
            variants[1],
            "明白，我看一下后回复你。",
            "low",
            "短句，不额外承诺。",
        ),
        ReplySuggestion(
            variants[2],
            f"关于“{_clip(base, 28)}”，我需要先核对时间和影响，再给你准确答复。",
            "medium",
            "用于需要边界感或需要核实事实的场景。",
        ),
    ]
    return ReplyGenerationResult(True, "local_preview", suggestions, "Local Preview")


def _generate_openai_compatible(context: ReplyContext, config: AppConfig) -> ReplyGenerationResult:
    endpoint = _chat_completions_endpoint(config.ai.base_url)
    preview = build_prompt_preview(context, config)
    payload = {
        "model": config.ai.model,
        "temperature": config.ai.temperature,
        "messages": [
            {"role": "system", "content": preview.system_prompt},
            {"role": "user", "content": preview.user_prompt},
        ],
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=_provider_headers(config.ai.api_key),
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=config.ai.timeout_seconds) as response:
            raw_body = response.read().decode("utf-8")
            _log_ai_provider(endpoint, _elapsed_ms(started), "http_ok", f"status={getattr(response, 'status', '-')}")
            data = json.loads(raw_body)
    except urllib.error.HTTPError as exc:
        body = _read_http_error_body(exc)
        _log_ai_provider(endpoint, _elapsed_ms(started), f"http_error:{exc.code}", f"reason={exc.reason} body={_clip(body, 500)}")
        return ReplyGenerationResult(False, f"AI 请求失败：{_http_error_message(exc.code, exc.reason, body)}", [], config.ai.provider)
    except (urllib.error.URLError, TimeoutError) as exc:
        _log_ai_provider(endpoint, _elapsed_ms(started), "transport_error", str(exc))
        return ReplyGenerationResult(False, f"AI 请求失败：{exc}", [], config.ai.provider)
    except json.JSONDecodeError as exc:
        _log_ai_provider(endpoint, _elapsed_ms(started), "bad_response_json", str(exc))
        return ReplyGenerationResult(False, f"AI 返回不是合法 JSON：{exc}", [], config.ai.provider)

    try:
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    except (AttributeError, IndexError):
        _log_ai_provider(endpoint, _elapsed_ms(started), "bad_response_shape", _clip(str(data), 240))
        return ReplyGenerationResult(False, "AI 返回结构无法解析", [], config.ai.provider)
    try:
        parsed = json.loads(content) if isinstance(content, str) else content
    except json.JSONDecodeError:
        _log_ai_provider(endpoint, _elapsed_ms(started), "bad_content_json", _clip(str(content), 240))
        return ReplyGenerationResult(False, "AI 返回格式无法解析", [], config.ai.provider)
    if not isinstance(parsed, dict):
        _log_ai_provider(endpoint, _elapsed_ms(started), "bad_content_type", type(parsed).__name__)
        return ReplyGenerationResult(False, "AI 返回格式无法解析", [], config.ai.provider)

    suggestions = [
        ReplySuggestion(
            label=str(item.get("label", f"候选 {index + 1}"))[:24],
            text=str(item.get("text", "")).strip(),
            risk=str(item.get("risk", "medium"))[:16],
            rationale=str(item.get("rationale", "")).strip(),
        )
        for index, item in enumerate(parsed.get("suggestions", [])[:3])
        if str(item.get("text", "")).strip()
    ]
    if not suggestions:
        _log_ai_provider(endpoint, _elapsed_ms(started), "empty_suggestions", _clip(str(parsed), 240))
        return ReplyGenerationResult(False, "AI 没有返回可用候选", [], config.ai.provider)
    _log_ai_provider(endpoint, _elapsed_ms(started), "parsed", f"suggestions={len(suggestions)}")
    return ReplyGenerationResult(True, "ai_generated", suggestions, config.ai.provider)


def _variants(value: str) -> list[str]:
    items = [item.strip() for item in value.split(",") if item.strip()]
    return (items + ["稳妥版", "简短版", "边界版"])[:3]


def _clip(value: str, max_len: int) -> str:
    return value if len(value) <= max_len else value[: max_len - 1] + "..."


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _chat_completions_endpoint(base_url: str) -> str:
    value = base_url.strip().rstrip("/")
    if value.endswith("/chat/completions"):
        return value
    return value + "/chat/completions"


def _http_error_message(code: int, reason: str, body: str = "") -> str:
    detail = _provider_error_detail(body)
    if code == 401:
        return "HTTP 401：认证失败，请检查 API Key 是否属于当前服务商，接口地址是否填到对应 Provider 的 /v1"
    if code == 403:
        return "HTTP 403：服务商拒绝访问；若其他软件可用，请核对 Base URL、模型名、账号/模型权限，或服务商是否限制请求头/IP"
    if code == 404:
        return "HTTP 404：接口或模型不存在，请检查接口地址和模型名称"
    if code == 429:
        return "HTTP 429：请求过于频繁或额度不足，请稍后重试或检查服务商额度"
    if detail:
        return f"HTTP {code}: {detail}"
    return f"HTTP {code}: {reason}"


def _read_http_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def _provider_error_detail(body: str) -> str:
    if not body.strip():
        return ""
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return _clip(" ".join(body.split()), 240)
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        message = str(error.get("message") or "").strip()
        code = str(error.get("code") or "").strip()
        if message and code:
            return f"{message} ({code})"
        if message:
            return message
    if isinstance(data, dict):
        message = str(data.get("message") or data.get("detail") or "").strip()
        if message:
            return message
    return _clip(str(data), 240)


def _provider_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "WhoChat/0.1 OpenAI-Compatible-Client",
    }


def _log_ai_provider(endpoint: str, elapsed_ms: int, status: str, detail: str) -> None:
    parsed = urllib.parse.urlparse(endpoint)
    target = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    clipped = " ".join(str(detail).split())[:800]
    append_diagnostics_log("ai_provider", f"target={target} elapsed_ms={elapsed_ms} status={status} {clipped}")
