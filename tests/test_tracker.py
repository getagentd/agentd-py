"""Tests for agentd.tracker"""

import pytest
from dataclasses import dataclass
from typing import Optional, Any

from agentd.tracker import AgentTracker
from agentd.models import RunStatus, EventType
from agentd.config import AgentDConfig, OutputMode, reset_config


# Mock SDK message types - names must match exactly what tracker expects
@dataclass
class AssistantMessage:
    content: list
    model: Optional[str] = None
    error: Optional[str] = None


@dataclass
class TextBlock:
    text: str


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict


@dataclass
class ToolResultBlock:
    tool_use_id: str
    content: str
    is_error: Optional[bool] = None


@dataclass
class ResultMessage:
    result: str
    duration_ms: Optional[int] = None
    duration_api_ms: Optional[int] = None
    num_turns: Optional[int] = None
    total_cost_usd: Optional[float] = None
    session_id: Optional[str] = None
    is_error: bool = False
    usage: Optional[Any] = None


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass
class ThinkingBlock:
    thinking: str


@dataclass
class UserMessage:
    content: list


@dataclass
class SystemMessage:
    subtype: str
    data: dict


@dataclass
class StreamEvent:
    event: dict
    session_id: Optional[str] = None


@pytest.fixture(autouse=True)
def reset_global_config():
    """Reset global config before each test."""
    reset_config()
    yield
    reset_config()


class TestAgentTrackerInit:
    def test_default_initialization(self):
        tracker = AgentTracker()
        assert tracker.run.status == RunStatus.RUNNING
        assert tracker.run.run_id is not None
        assert len(tracker.run.events) == 1  # RUN_START event
        assert tracker.run.events[0].type == EventType.RUN_START

    def test_with_agent_id(self):
        tracker = AgentTracker(agent_id="test-agent")
        assert tracker.run.agent_id == "test-agent"

    def test_with_session_id(self):
        tracker = AgentTracker(session_id="session-123")
        assert tracker.run.session_id == "session-123"

    def test_with_metadata(self):
        tracker = AgentTracker(metadata={"env": "test", "version": "1.0"})
        assert tracker.run.metadata["env"] == "test"
        assert tracker.run.metadata["version"] == "1.0"

    def test_prompt_included_when_configured(self):
        config = AgentDConfig(include_prompt=True)
        tracker = AgentTracker(prompt="Test prompt", config=config)
        assert tracker.run.prompt == "Test prompt"

    def test_prompt_excluded_by_default(self):
        tracker = AgentTracker(prompt="Test prompt")
        assert tracker.run.prompt is None


class TestProcessMessage:
    def test_assistant_message_extracts_model(self):
        tracker = AgentTracker()
        msg = AssistantMessage(content=[], model="claude-sonnet-4-5-20250929")
        tracker.process_message(msg)
        assert tracker.run.model == "claude-sonnet-4-5-20250929"

    def test_assistant_message_with_text(self):
        config = AgentDConfig(include_trace=True)
        tracker = AgentTracker(config=config)
        msg = AssistantMessage(
            content=[TextBlock(text="Hello, world!")],
            model="claude-sonnet-4-5-20250929",
        )
        tracker.process_message(msg)

        events = [e for e in tracker.run.events if e.type == EventType.ASSISTANT_MESSAGE]
        assert len(events) == 1
        assert events[0].content == "Hello, world!"

    def test_tool_use_block_standalone(self):
        config = AgentDConfig(include_trace=True, include_tool_inputs=True)
        tracker = AgentTracker(config=config)

        block = ToolUseBlock(
            id="tool_123",
            name="Read",
            input={"file_path": "/tmp/test.txt"},
        )
        tracker.process_message(block)

        events = [e for e in tracker.run.events if e.type == EventType.TOOL_CALL]
        assert len(events) == 1
        assert events[0].tool_name == "Read"
        assert events[0].tool_id == "tool_123"
        assert events[0].tool_input == {"file_path": "/tmp/test.txt"}

    def test_tool_use_block_in_assistant_message(self):
        config = AgentDConfig(include_trace=True, include_tool_inputs=True)
        tracker = AgentTracker(config=config)

        msg = AssistantMessage(
            content=[ToolUseBlock(id="tool_456", name="Bash", input={"command": "ls"})],
            model="claude-sonnet-4-5-20250929",
        )
        tracker.process_message(msg)

        events = [e for e in tracker.run.events if e.type == EventType.TOOL_CALL]
        assert len(events) == 1
        assert events[0].tool_name == "Bash"

    def test_tool_result_block_via_user_message(self):
        config = AgentDConfig(include_trace=True, include_tool_outputs=True)
        tracker = AgentTracker(config=config)

        # First, register a tool use
        tool_use = ToolUseBlock(id="tool_123", name="Read", input={})
        tracker.process_message(tool_use)

        # Then send the result via UserMessage (as the SDK does)
        result_block = ToolResultBlock(
            tool_use_id="tool_123",
            content="File contents here",
            is_error=False,
        )
        user_msg = UserMessage(content=[result_block])
        tracker.process_message(user_msg)

        events = [e for e in tracker.run.events if e.type == EventType.TOOL_RESULT]
        assert len(events) == 1
        assert events[0].tool_name == "Read"
        assert events[0].tool_id == "tool_123"
        assert events[0].tool_success is True
        assert events[0].tool_output == "File contents here"

    def test_tool_result_error(self):
        config = AgentDConfig(include_trace=True)
        tracker = AgentTracker(config=config)

        tool_use = ToolUseBlock(id="tool_456", name="Bash", input={})
        tracker.process_message(tool_use)

        result_block = ToolResultBlock(
            tool_use_id="tool_456",
            content="Command failed",
            is_error=True,
        )
        user_msg = UserMessage(content=[result_block])
        tracker.process_message(user_msg)

        events = [e for e in tracker.run.events if e.type == EventType.TOOL_RESULT]
        assert len(events) == 1
        assert events[0].tool_success is False

    def test_result_message_extracts_usage(self):
        tracker = AgentTracker()

        usage = Usage(
            input_tokens=1000,
            output_tokens=500,
            cache_read_input_tokens=200,
            cache_creation_input_tokens=100,
        )
        msg = ResultMessage(
            result="Done",
            usage=usage,
            duration_ms=5000,
            num_turns=3,
            total_cost_usd=0.05,
            session_id="sdk-session-123",
        )
        tracker.process_message(msg)

        assert tracker.run.tokens.input == 1000
        assert tracker.run.tokens.output == 500
        assert tracker.run.tokens.cache_read == 200
        assert tracker.run.tokens.cache_write == 100
        assert tracker.run.duration_ms == 5000
        assert tracker.run.num_turns == 3
        assert tracker.run.sdk_cost_usd == 0.05
        assert tracker.run.sdk_session_id == "sdk-session-123"

    def test_thinking_block_in_assistant_message(self):
        config = AgentDConfig(include_trace=True)
        tracker = AgentTracker(config=config)

        msg = AssistantMessage(
            content=[ThinkingBlock(thinking="Let me think about this...")],
            model="claude-sonnet-4-5-20250929",
        )
        tracker.process_message(msg)

        events = [e for e in tracker.run.events if e.type == EventType.THINKING]
        assert len(events) == 1
        assert events[0].thinking == "Let me think about this..."

    def test_system_message(self):
        config = AgentDConfig(include_trace=True)
        tracker = AgentTracker(config=config)

        msg = SystemMessage(subtype="init", data={"version": "1.0"})
        tracker.process_message(msg)

        events = [e for e in tracker.run.events if e.type == EventType.SYSTEM_MESSAGE]
        assert len(events) == 1
        assert "init" in events[0].content

    def test_stream_event(self):
        config = AgentDConfig(include_trace=True)
        tracker = AgentTracker(config=config)

        msg = StreamEvent(event={"type": "partial"}, session_id="stream-123")
        tracker.process_message(msg)

        events = [e for e in tracker.run.events if e.type == EventType.STREAM_EVENT]
        assert len(events) == 1
        assert tracker.run.sdk_session_id == "stream-123"


class TestEventSequencing:
    def test_events_have_incrementing_sequence_numbers(self):
        config = AgentDConfig(include_trace=True)
        tracker = AgentTracker(config=config)

        # Process multiple messages
        tracker.process_message(AssistantMessage(content=[TextBlock("Hi")]))
        tracker.process_message(ToolUseBlock(id="t1", name="Read", input={}))
        tracker.process_message(UserMessage(content=[
            ToolResultBlock(tool_use_id="t1", content="result")
        ]))

        sequences = [e.sequence_number for e in tracker.run.events]
        # Should be strictly increasing
        assert sequences == sorted(sequences)
        assert len(set(sequences)) == len(sequences)  # All unique


class TestToolStats:
    def test_tool_stats_aggregation(self):
        config = AgentDConfig(include_trace=True)
        tracker = AgentTracker(config=config)

        # Simulate multiple tool calls
        for i in range(3):
            tracker.process_message(ToolUseBlock(id=f"read_{i}", name="Read", input={}))
            tracker.process_message(UserMessage(content=[
                ToolResultBlock(tool_use_id=f"read_{i}", content="ok")
            ]))

        tracker.process_message(ToolUseBlock(id="bash_1", name="Bash", input={}))
        tracker.process_message(UserMessage(content=[
            ToolResultBlock(tool_use_id="bash_1", content="ok")
        ]))

        tracker.finish()

        # Check tool summaries
        assert len(tracker.run.tool_calls) == 2

        read_summary = next(tc for tc in tracker.run.tool_calls if tc.tool == "Read")
        assert read_summary.count == 3
        assert read_summary.success_count == 3
        assert read_summary.failure_count == 0

        bash_summary = next(tc for tc in tracker.run.tool_calls if tc.tool == "Bash")
        assert bash_summary.count == 1


class TestFinish:
    def test_finish_sets_completed_status(self):
        tracker = AgentTracker()
        tracker.finish()
        assert tracker.run.status == RunStatus.COMPLETED

    def test_finish_with_explicit_status(self):
        tracker = AgentTracker()
        tracker.finish(RunStatus.TIMEOUT)
        assert tracker.run.status == RunStatus.TIMEOUT

    def test_finish_sets_failed_on_error(self):
        tracker = AgentTracker()
        tracker.record_error(ValueError("test error"))
        tracker.finish()
        assert tracker.run.status == RunStatus.FAILED

    def test_finish_sets_duration(self):
        tracker = AgentTracker()
        tracker.finish()
        assert tracker.run.duration_ms is not None
        assert tracker.run.duration_ms >= 0

    def test_finish_sets_finished_at(self):
        tracker = AgentTracker()
        tracker.finish()
        assert tracker.run.finished_at is not None

    def test_finish_calculates_estimated_cost(self):
        tracker = AgentTracker()
        tracker.run.tokens.input = 1000
        tracker.run.tokens.output = 500
        tracker.run.model = "claude-sonnet-4-5-20250929"
        tracker.finish()
        assert tracker.run.estimated_cost_usd is not None
        assert tracker.run.estimated_cost_usd > 0


class TestRecordError:
    def test_record_error_creates_error_info(self):
        tracker = AgentTracker()
        tracker.record_error(ValueError("Something went wrong"))

        assert tracker.run.error is not None
        assert tracker.run.error.type == "ValueError"
        assert tracker.run.error.message == "Something went wrong"

    def test_record_error_adds_event(self):
        config = AgentDConfig(include_trace=True)
        tracker = AgentTracker(config=config)
        tracker.record_error(RuntimeError("Oops"))

        events = [e for e in tracker.run.events if e.type == EventType.ERROR]
        assert len(events) == 1


class TestTruncation:
    def test_long_content_is_truncated(self):
        config = AgentDConfig(include_trace=True, truncate_outputs_at=100)
        tracker = AgentTracker(config=config)

        long_text = "x" * 500
        msg = AssistantMessage(content=[TextBlock(text=long_text)])
        tracker.process_message(msg)

        events = [e for e in tracker.run.events if e.type == EventType.ASSISTANT_MESSAGE]
        assert len(events) == 1
        assert len(events[0].content) < 500
        assert "truncated" in events[0].content


class TestShip:
    @pytest.mark.asyncio
    async def test_ship_console_mode(self, capsys):
        config = AgentDConfig(include_trace=True)
        tracker = AgentTracker(agent_id="test-agent", config=config)
        tracker.run.tokens.input = 1000
        tracker.run.tokens.output = 500
        tracker.finish()

        result = await tracker.ship()
        assert result is True

        captured = capsys.readouterr()
        assert "AGENT RUN SUMMARY" in captured.out
        assert "test-agent" in captured.out

    @pytest.mark.asyncio
    async def test_ship_disabled_mode(self):
        config = AgentDConfig(disabled=True)
        tracker = AgentTracker(config=config)
        tracker.finish()

        result = await tracker.ship()
        assert result is True
