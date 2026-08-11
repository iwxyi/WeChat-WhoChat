from __future__ import annotations

import re
from dataclasses import dataclass

from whochat.ai.models import ReplyContext
from whochat.config import AppConfig


@dataclass(frozen=True)
class PromptPreview:
    provider: str
    model: str
    system_prompt: str
    user_prompt: str
    redaction_applied: bool
    redaction_summary: str
    message_count: int
    memory_count: int

    @property
    def combined_text(self) -> str:
        return f"[system]\n{self.system_prompt}\n\n[user]\n{self.user_prompt}"


def build_prompt_preview(context: ReplyContext, config: AppConfig) -> PromptPreview:
    raw_system = system_prompt(context)
    raw_user = user_prompt(context)
    redacted_system, system_counts = redact_sensitive_text(raw_system) if config.privacy.trim_context_for_cloud else (raw_system, {})
    redacted_user, user_counts = redact_sensitive_text(raw_user) if config.privacy.trim_context_for_cloud else (raw_user, {})
    counts = _merge_counts(system_counts, user_counts)
    return PromptPreview(
        provider=config.ai.provider,
        model=config.ai.model,
        system_prompt=redacted_system,
        user_prompt=redacted_user,
        redaction_applied=bool(counts),
        redaction_summary=_redaction_summary(counts),
        message_count=len(context.messages),
        memory_count=len(context.memories),
    )


def system_prompt(context: ReplyContext) -> str:
    strategy = context.strategy
    return "\n".join(
        [
            "你是本地桌面聊天助手，只生成用户可审核后复制的回复候选。",
            "必须输出 JSON：{\"suggestions\":[{\"label\":\"\",\"text\":\"\",\"risk\":\"low|medium|high\",\"rationale\":\"\"}]}",
            f"目标：{strategy.goal if strategy else '自然、稳妥'}",
            f"语气：{strategy.tone if strategy else '自然、清晰'}",
            f"禁忌：{strategy.avoid if strategy else '不要过度承诺，不要伪造事实'}",
        ]
    )


def user_prompt(context: ReplyContext) -> str:
    messages = "\n".join(f"{_message_speaker_label(m)}: {m.text}" for m in context.messages[-20:])
    memories = "\n".join(f"- {m.kind.value}: {m.content}" for m in context.memories[:20])
    contact = context.contact.display_name if context.contact else "未知联系人"
    return f"联系人：{contact}\n\n长期记忆：\n{memories or '-'}\n\n最近聊天：\n{messages or '-'}"


def _message_speaker_label(message) -> str:
    if getattr(message, "sender_name", ""):
        return f"{message.speaker.value}({message.sender_name})"
    return message.speaker.value


def redact_sensitive_text(value: str) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}

    def replace(pattern: str, label: str, text: str) -> str:
        def repl(_match: re.Match[str]) -> str:
            counts[label] = counts.get(label, 0) + 1
            return f"[已脱敏:{label}]"

        return re.sub(pattern, repl, text)

    redacted = value
    redacted = replace(r"sk-[A-Za-z0-9_-]{12,}", "密钥", redacted)
    redacted = replace(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "邮箱", redacted)
    redacted = replace(r"https?://[^\s]+", "链接", redacted)
    redacted = replace(r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d{9}(?!\d)", "手机号", redacted)
    redacted = replace(r"(?<!\d)\d{12,}(?!\d)", "长数字", redacted)
    return redacted, counts


def _merge_counts(*items: dict[str, int]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for item in items:
        for key, value in item.items():
            merged[key] = merged.get(key, 0) + value
    return merged


def _redaction_summary(counts: dict[str, int]) -> str:
    if not counts:
        return "未发现需脱敏内容"
    return "，".join(f"{key}:{value}" for key, value in sorted(counts.items()))
