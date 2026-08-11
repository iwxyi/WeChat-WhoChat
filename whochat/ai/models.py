from __future__ import annotations

from dataclasses import dataclass

from whochat.core.models import Contact, Memory, Message, Strategy
from whochat.core.runtime import RuntimeState


@dataclass(frozen=True)
class ReplyContext:
    runtime: RuntimeState
    contact: Contact | None
    strategy: Strategy | None
    messages: list[Message]
    memories: list[Memory]


@dataclass(frozen=True)
class ReplySuggestion:
    label: str
    text: str
    risk: str
    rationale: str


@dataclass(frozen=True)
class ReplyGenerationResult:
    allowed: bool
    status: str
    suggestions: list[ReplySuggestion]
    provider: str


@dataclass(frozen=True)
class AIConnectionTestResult:
    ok: bool
    status: str
    provider: str
    detail: str
    elapsed_ms: int = 0
