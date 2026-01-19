"""
Data models for agent metrics.

These models define the API contract. Self-hosters can implement receivers
that accept these structures.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional, Any
from enum import Enum
import uuid
import secrets


class RunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


class EventType(str, Enum):
    RUN_START = "run_start"
    ASSISTANT_MESSAGE = "assistant_message"
    THINKING = "thinking"  # Extended thinking blocks
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ERROR = "error"
    API_ERROR = "api_error"  # Rate limits, auth failures, etc.
    RUN_END = "run_end"
    # Additional message types for comprehensive tracking
    STREAM_EVENT = "stream_event"  # Partial streaming updates
    SYSTEM_MESSAGE = "system_message"  # SDK system messages with metadata
    USER_MESSAGE = "user_message"  # Multi-turn user inputs


@dataclass
class TokenUsage:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0

    def total(self) -> int:
        return self.input + self.output

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            input=self.input + other.input,
            output=self.output + other.output,
            cache_read=self.cache_read + other.cache_read,
            cache_write=self.cache_write + other.cache_write,
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ToolCallSummary:
    tool: str
    count: int = 0
    total_duration_ms: int = 0
    success_count: int = 0
    failure_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ErrorInfo:
    type: str
    message: str
    stack: Optional[str] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class RunEvent:
    """A single event in an agent run trace."""

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: EventType = EventType.RUN_START
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat() + "Z")
    sequence_number: int = 0  # For reliable message ordering

    # For tool events
    tool_name: Optional[str] = None
    tool_id: Optional[str] = None  # ToolUseBlock.id for correlation
    tool_input: Optional[dict] = None
    tool_output: Optional[str] = None
    tool_duration_ms: Optional[int] = None
    tool_success: Optional[bool] = None

    # For message events
    content: Optional[str] = None
    tokens: Optional[TokenUsage] = None

    # For thinking events
    thinking: Optional[str] = None

    # For error events
    error: Optional[ErrorInfo] = None

    def to_dict(self) -> dict:
        result = {
            "event_id": self.event_id,
            "type": self.type.value if isinstance(self.type, EventType) else self.type,
            "timestamp": self.timestamp,
            "sequence_number": self.sequence_number,
        }

        if self.tool_name is not None:
            result["tool_name"] = self.tool_name
        if self.tool_id is not None:
            result["tool_id"] = self.tool_id
        if self.tool_input is not None:
            result["tool_input"] = self.tool_input
        if self.tool_output is not None:
            result["tool_output"] = self.tool_output
        if self.tool_duration_ms is not None:
            result["tool_duration_ms"] = self.tool_duration_ms
        if self.tool_success is not None:
            result["tool_success"] = self.tool_success
        if self.content is not None:
            result["content"] = self.content
        if self.tokens is not None:
            result["tokens"] = self.tokens.to_dict()
        if self.thinking is not None:
            result["thinking"] = self.thinking
        if self.error is not None:
            result["error"] = self.error.to_dict()

        return result


@dataclass
class AgentRun:
    """Complete record of an agent run."""

    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: Optional[str] = None
    session_id: Optional[str] = None

    # Timing
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat() + "Z")
    finished_at: Optional[str] = None
    duration_ms: Optional[int] = None
    api_duration_ms: Optional[int] = None  # API-specific duration from SDK
    first_token_ms: Optional[int] = None  # Time to first token (TTFT)

    # Status
    status: RunStatus = RunStatus.RUNNING
    error: Optional[ErrorInfo] = None
    num_turns: Optional[int] = None  # Number of conversation turns

    # Usage
    tokens: TokenUsage = field(default_factory=TokenUsage)
    estimated_cost_usd: Optional[float] = None
    sdk_cost_usd: Optional[float] = None  # Cost from SDK (more accurate)
    model: Optional[str] = None

    # SDK session info
    sdk_session_id: Optional[str] = None  # Session ID from SDK

    # OpenTelemetry-compatible trace context
    trace_id: str = field(default_factory=lambda: secrets.token_hex(16))  # 32 char hex
    span_id: str = field(default_factory=lambda: secrets.token_hex(8))    # 16 char hex
    parent_span_id: Optional[str] = None  # For nested runs

    # Tool usage summary
    tool_calls: list[ToolCallSummary] = field(default_factory=list)

    # Full trace
    events: list[RunEvent] = field(default_factory=list)

    # User-defined metadata
    metadata: dict[str, Any] = field(default_factory=dict)

    # Original prompt (optional, for debugging)
    prompt: Optional[str] = None

    def to_dict(self) -> dict:
        result = {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "status": self.status.value if isinstance(self.status, RunStatus) else self.status,
            "tokens": self.tokens.to_dict(),
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
            "events": [e.to_dict() for e in self.events],
            # OpenTelemetry trace context (always present)
            "trace_id": self.trace_id,
            "span_id": self.span_id,
        }

        # Preferred cost: SDK is authoritative, fall back to estimate
        cost_usd = self.sdk_cost_usd or self.estimated_cost_usd
        if cost_usd is not None:
            result["cost_usd"] = cost_usd
            result["cost_source"] = "sdk" if self.sdk_cost_usd else "estimated"

        if self.agent_id is not None:
            result["agent_id"] = self.agent_id
        if self.session_id is not None:
            result["session_id"] = self.session_id
        if self.finished_at is not None:
            result["finished_at"] = self.finished_at
        if self.duration_ms is not None:
            result["duration_ms"] = self.duration_ms
        if self.api_duration_ms is not None:
            result["api_duration_ms"] = self.api_duration_ms
        if self.first_token_ms is not None:
            result["first_token_ms"] = self.first_token_ms
        if self.num_turns is not None:
            result["num_turns"] = self.num_turns
        if self.error is not None:
            result["error"] = self.error.to_dict()
        if self.estimated_cost_usd is not None:
            result["estimated_cost_usd"] = self.estimated_cost_usd
        if self.sdk_cost_usd is not None:
            result["sdk_cost_usd"] = self.sdk_cost_usd
        if self.sdk_session_id is not None:
            result["sdk_session_id"] = self.sdk_session_id
        if self.parent_span_id is not None:
            result["parent_span_id"] = self.parent_span_id
        if self.model is not None:
            result["model"] = self.model
        if self.metadata:
            result["metadata"] = self.metadata
        if self.prompt is not None:
            result["prompt"] = self.prompt

        return result


# Pricing per 1M tokens (as of late 2025, update as needed)
MODEL_PRICING = {
    "claude-sonnet-4-5-20250929": {"input": 3.0, "output": 15.0},
    "claude-opus-4-5-20251101": {"input": 15.0, "output": 75.0},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0},
    # Fallback for unknown models
    "default": {"input": 3.0, "output": 15.0},
}


def estimate_cost(tokens: TokenUsage, model: Optional[str] = None) -> float:
    """Estimate cost in USD based on token usage."""
    pricing = MODEL_PRICING.get(model, MODEL_PRICING["default"])

    input_cost = (tokens.input / 1_000_000) * pricing["input"]
    output_cost = (tokens.output / 1_000_000) * pricing["output"]

    # Cache reads are typically 90% cheaper
    cache_read_cost = (tokens.cache_read / 1_000_000) * pricing["input"] * 0.1

    return round(input_cost + output_cost + cache_read_cost, 6)