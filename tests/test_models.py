"""Tests for agentd.models"""

import pytest
from agentd.models import (
    TokenUsage,
    ToolCallSummary,
    ErrorInfo,
    RunEvent,
    AgentRun,
    RunStatus,
    EventType,
    estimate_cost,
    MODEL_PRICING,
)


class TestTokenUsage:
    def test_default_values(self):
        usage = TokenUsage()
        assert usage.input == 0
        assert usage.output == 0
        assert usage.cache_read == 0
        assert usage.cache_write == 0

    def test_total(self):
        usage = TokenUsage(input=100, output=50)
        assert usage.total() == 150

    def test_addition(self):
        usage1 = TokenUsage(input=100, output=50, cache_read=10, cache_write=5)
        usage2 = TokenUsage(input=200, output=100, cache_read=20, cache_write=10)
        combined = usage1 + usage2
        assert combined.input == 300
        assert combined.output == 150
        assert combined.cache_read == 30
        assert combined.cache_write == 15

    def test_to_dict(self):
        usage = TokenUsage(input=100, output=50)
        d = usage.to_dict()
        assert d["input"] == 100
        assert d["output"] == 50
        assert d["cache_read"] == 0
        assert d["cache_write"] == 0


class TestToolCallSummary:
    def test_default_values(self):
        summary = ToolCallSummary(tool="Read")
        assert summary.tool == "Read"
        assert summary.count == 0
        assert summary.total_duration_ms == 0
        assert summary.success_count == 0
        assert summary.failure_count == 0

    def test_to_dict(self):
        summary = ToolCallSummary(
            tool="Bash",
            count=5,
            total_duration_ms=1000,
            success_count=4,
            failure_count=1,
        )
        d = summary.to_dict()
        assert d["tool"] == "Bash"
        assert d["count"] == 5
        assert d["total_duration_ms"] == 1000
        assert d["success_count"] == 4
        assert d["failure_count"] == 1


class TestErrorInfo:
    def test_basic(self):
        error = ErrorInfo(type="ValueError", message="Something went wrong")
        assert error.type == "ValueError"
        assert error.message == "Something went wrong"
        assert error.stack is None

    def test_to_dict_excludes_none(self):
        error = ErrorInfo(type="ValueError", message="test")
        d = error.to_dict()
        assert "stack" not in d
        assert d["type"] == "ValueError"
        assert d["message"] == "test"

    def test_to_dict_includes_stack(self):
        error = ErrorInfo(type="ValueError", message="test", stack="line 1\nline 2")
        d = error.to_dict()
        assert d["stack"] == "line 1\nline 2"


class TestRunEvent:
    def test_default_values(self):
        event = RunEvent()
        assert event.type == EventType.RUN_START
        assert event.sequence_number == 0
        assert event.event_id is not None
        assert event.timestamp is not None

    def test_tool_event(self):
        event = RunEvent(
            type=EventType.TOOL_CALL,
            tool_name="Read",
            tool_id="tool_123",
            tool_input={"file_path": "/tmp/test.txt"},
        )
        assert event.type == EventType.TOOL_CALL
        assert event.tool_name == "Read"
        assert event.tool_id == "tool_123"
        assert event.tool_input == {"file_path": "/tmp/test.txt"}

    def test_to_dict_minimal(self):
        event = RunEvent(type=EventType.RUN_START)
        d = event.to_dict()
        assert d["type"] == "run_start"
        assert "event_id" in d
        assert "timestamp" in d
        assert "sequence_number" in d
        # Optional fields should not be present
        assert "tool_name" not in d
        assert "content" not in d

    def test_to_dict_with_tool_fields(self):
        event = RunEvent(
            type=EventType.TOOL_RESULT,
            tool_name="Bash",
            tool_id="tool_456",
            tool_output="success",
            tool_duration_ms=150,
            tool_success=True,
        )
        d = event.to_dict()
        assert d["type"] == "tool_result"
        assert d["tool_name"] == "Bash"
        assert d["tool_id"] == "tool_456"
        assert d["tool_output"] == "success"
        assert d["tool_duration_ms"] == 150
        assert d["tool_success"] is True


class TestAgentRun:
    def test_default_values(self):
        run = AgentRun()
        assert run.run_id is not None
        assert run.status == RunStatus.RUNNING
        assert run.tokens.input == 0
        assert run.tool_calls == []
        assert run.events == []
        assert run.metadata == {}

    def test_to_dict_minimal(self):
        run = AgentRun()
        d = run.to_dict()
        assert "run_id" in d
        assert "started_at" in d
        assert d["status"] == "running"
        assert "tokens" in d
        assert d["tool_calls"] == []
        assert d["events"] == []

    def test_to_dict_with_optional_fields(self):
        run = AgentRun(
            agent_id="test-agent",
            session_id="session-123",
            model="claude-sonnet-4-5-20250929",
            duration_ms=5000,
            estimated_cost_usd=0.05,
            metadata={"env": "test"},
        )
        d = run.to_dict()
        assert d["agent_id"] == "test-agent"
        assert d["session_id"] == "session-123"
        assert d["model"] == "claude-sonnet-4-5-20250929"
        assert d["duration_ms"] == 5000
        assert d["estimated_cost_usd"] == 0.05
        assert d["metadata"] == {"env": "test"}


class TestEstimateCost:
    def test_zero_tokens(self):
        usage = TokenUsage()
        cost = estimate_cost(usage)
        assert cost == 0.0

    def test_sonnet_pricing(self):
        usage = TokenUsage(input=1_000_000, output=1_000_000)
        cost = estimate_cost(usage, "claude-sonnet-4-5-20250929")
        # $3/M input + $15/M output = $18
        assert cost == 18.0

    def test_opus_pricing(self):
        usage = TokenUsage(input=1_000_000, output=1_000_000)
        cost = estimate_cost(usage, "claude-opus-4-5-20251101")
        # $15/M input + $75/M output = $90
        assert cost == 90.0

    def test_haiku_pricing(self):
        usage = TokenUsage(input=1_000_000, output=1_000_000)
        cost = estimate_cost(usage, "claude-haiku-4-5-20251001")
        # $0.80/M input + $4/M output = $4.80
        assert cost == 4.8

    def test_cache_read_discount(self):
        usage = TokenUsage(input=0, output=0, cache_read=1_000_000)
        cost = estimate_cost(usage, "claude-sonnet-4-5-20250929")
        # Cache reads are 90% cheaper: $3 * 0.1 = $0.30
        assert cost == 0.3

    def test_unknown_model_uses_default(self):
        usage = TokenUsage(input=1_000_000, output=1_000_000)
        cost = estimate_cost(usage, "unknown-model")
        # Default is sonnet pricing: $3/M + $15/M = $18
        assert cost == 18.0

    def test_small_token_count(self):
        usage = TokenUsage(input=1000, output=500)
        cost = estimate_cost(usage, "claude-sonnet-4-5-20250929")
        # $3 * 0.001 + $15 * 0.0005 = $0.003 + $0.0075 = $0.0105
        assert cost == 0.0105


class TestEnums:
    def test_run_status_values(self):
        assert RunStatus.RUNNING.value == "running"
        assert RunStatus.COMPLETED.value == "completed"
        assert RunStatus.FAILED.value == "failed"
        assert RunStatus.TIMEOUT.value == "timeout"

    def test_event_type_values(self):
        assert EventType.RUN_START.value == "run_start"
        assert EventType.ASSISTANT_MESSAGE.value == "assistant_message"
        assert EventType.THINKING.value == "thinking"
        assert EventType.TOOL_CALL.value == "tool_call"
        assert EventType.TOOL_RESULT.value == "tool_result"
        assert EventType.ERROR.value == "error"
        assert EventType.API_ERROR.value == "api_error"
        assert EventType.RUN_END.value == "run_end"
        assert EventType.STREAM_EVENT.value == "stream_event"
        assert EventType.SYSTEM_MESSAGE.value == "system_message"
        assert EventType.USER_MESSAGE.value == "user_message"
