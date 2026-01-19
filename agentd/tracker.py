"""
AgentTracker - Core tracking logic for agent runs.

This module intercepts messages from the Claude Agent SDK and extracts
metrics, traces, and usage information.
"""
from __future__ import annotations

import time
import asyncio
from datetime import datetime, timezone
from typing import Optional, Any
from collections import defaultdict

from .models import (
    AgentRun, RunEvent, TokenUsage, ToolCallSummary, ErrorInfo,
    RunStatus, EventType, estimate_cost
)
from .config import AgentDConfig, get_config, OutputMode
from .transport import send_run, send_event


class AgentTracker:
    """
    Tracks a single agent run and collects metrics.

    Usage:
        tracker = AgentTracker(agent_id="my-agent")

        async for message in original_query(...):
            tracker.process_message(message)
            yield message

        tracker.finish()
        await tracker.ship()
    """

    def __init__(
            self,
            agent_id: Optional[str] = None,
            session_id: Optional[str] = None,
            prompt: Optional[str] = None,
            metadata: Optional[dict] = None,
            config: Optional[AgentDConfig] = None,
    ):
        self.config = config or get_config()

        self.run = AgentRun(
            agent_id=agent_id or self.config.agent_id,
            session_id=session_id or self.config.session_id,
            prompt=prompt if self.config.include_prompt else None,
            metadata={**self.config.default_metadata, **(metadata or {})},
        )

        self._start_time = time.time()
        self._first_token_time: Optional[float] = None  # For TTFT tracking
        self._tool_stats: dict[str, dict] = defaultdict(
            lambda: {"count": 0, "duration_ms": 0, "success": 0, "failure": 0}
        )
        # Track pending tools by ID for proper correlation with results
        self._pending_tools: dict[str, dict] = {}  # tool_id -> {name, start_time}
        self._message_sequence: int = 0  # For reliable event ordering

        # Record start event
        self._add_event(RunEvent(type=EventType.RUN_START))

    def _add_event(self, event: RunEvent):
        """Add an event to the trace."""
        # Set sequence number for reliable ordering
        event.sequence_number = self._message_sequence
        self._message_sequence += 1

        if self.config.include_trace:
            self.run.events.append(event)

        # If streaming mode, ship event immediately
        if self.config.streaming and self.config.mode == OutputMode.HTTP:
            asyncio.create_task(send_event(self.run.run_id, event, self.config))

    def _truncate(self, text: str) -> str:
        """Truncate text to configured limit."""
        if len(text) > self.config.truncate_outputs_at:
            return text[
                :self.config.truncate_outputs_at] + f"... [truncated {len(text) - self.config.truncate_outputs_at} chars]"
        return text

    def process_message(self, message: Any) -> None:
        """
        Process a message from the Claude Agent SDK and extract metrics.

        This handles ALL message types from claude_agent_sdk:
        - AssistantMessage: Claude's responses (always extracts model)
        - ToolUseBlock: Tool invocations
        - ToolResultBlock: Tool results
        - ResultMessage: Final result with usage info
        - StreamEvent: Partial streaming updates
        - SystemMessage: SDK system messages with metadata
        - UserMessage: Multi-turn user inputs
        """
        message_type = type(message).__name__

        # Always extract model from AssistantMessage (updates on every message)
        if message_type == "AssistantMessage" and hasattr(message, 'model') and message.model:
            self.run.model = message.model

        # Handle ALL message types
        if message_type == "AssistantMessage":
            self._handle_assistant_message(message)

        elif message_type == "ToolUseBlock":
            self._handle_tool_use(message)

        elif message_type == "ToolResultBlock":
            self._handle_tool_result(message)

        elif message_type == "ResultMessage":
            self._handle_result(message)

        elif message_type == "StreamEvent":
            self._handle_stream_event(message)

        elif message_type == "SystemMessage":
            self._handle_system_message(message)

        elif message_type == "UserMessage":
            self._handle_user_message(message)

        # Note: Usage info is extracted in _handle_result() where it actually exists

    def _handle_assistant_message(self, message: Any) -> None:
        """Handle an assistant message."""
        # Track Time to First Token (TTFT)
        if self._first_token_time is None:
            self._first_token_time = time.time()
            self.run.first_token_ms = int((self._first_token_time - self._start_time) * 1000)

        # Check for API errors (rate limits, auth failures, etc.)
        if hasattr(message, 'error') and message.error:
            self._add_event(RunEvent(
                type=EventType.API_ERROR,
                content=str(message.error),
            ))

        content_text = ""

        if hasattr(message, 'content'):
            for block in message.content:
                block_type = type(block).__name__

                if block_type == "ThinkingBlock":
                    # Handle extended thinking blocks
                    self._handle_thinking(block)
                elif block_type == "ToolUseBlock" or hasattr(block, 'name'):
                    # This is a tool use block embedded in assistant message
                    self._handle_tool_use(block)
                elif hasattr(block, 'text'):
                    content_text += block.text

        if content_text:
            self._add_event(RunEvent(
                type=EventType.ASSISTANT_MESSAGE,
                content=self._truncate(content_text),
            ))

    def _handle_thinking(self, block: Any) -> None:
        """Handle an extended thinking block."""
        thinking_text = getattr(block, 'thinking', '')

        if thinking_text:
            self._add_event(RunEvent(
                type=EventType.THINKING,
                thinking=self._truncate(thinking_text),
            ))

    def _handle_stream_event(self, message: Any) -> None:
        """Handle streaming partial updates."""
        event_data = getattr(message, 'event', {})
        session_id = getattr(message, 'session_id', None)

        # Store SDK session ID if available
        if session_id and not self.run.sdk_session_id:
            self.run.sdk_session_id = session_id

        self._add_event(RunEvent(
            type=EventType.STREAM_EVENT,
            content=str(event_data)[:500],  # Truncate for size
        ))

    def _handle_system_message(self, message: Any) -> None:
        """Handle SDK system messages with metadata."""
        subtype = getattr(message, 'subtype', 'unknown')
        data = getattr(message, 'data', {})

        self._add_event(RunEvent(
            type=EventType.SYSTEM_MESSAGE,
            content=f"{subtype}: {str(data)[:200]}",
        ))

    def _handle_user_message(self, message: Any) -> None:
        """Handle user messages in multi-turn conversations.

        Note: Tool results are delivered as UserMessage with ToolResultBlock in content.
        """
        if not hasattr(message, 'content'):
            return

        content_text = ""
        has_tool_result = False

        if isinstance(message.content, str):
            content_text = message.content
        elif isinstance(message.content, list):
            for block in message.content:
                block_type = type(block).__name__

                # Check for tool result blocks (SDK wraps them in UserMessage)
                if block_type == "ToolResultBlock" or hasattr(block, 'tool_use_id'):
                    has_tool_result = True
                    self._handle_tool_result(block)
                elif hasattr(block, 'text'):
                    content_text += block.text

        # Only record as user message if it's actual user input, not tool results
        if content_text and not has_tool_result:
            self._add_event(RunEvent(
                type=EventType.USER_MESSAGE,
                content=self._truncate(content_text),
            ))

    def _handle_tool_use(self, block: Any) -> None:
        """Handle a tool use block."""
        tool_id = getattr(block, 'id', None)
        tool_name = getattr(block, 'name', 'unknown')
        tool_input = getattr(block, 'input', {})

        # Track pending tool for correlation with result
        if tool_id:
            self._pending_tools[tool_id] = {
                "name": tool_name,
                "start_time": time.time(),
            }

        event = RunEvent(
            type=EventType.TOOL_CALL,
            tool_name=tool_name,
            tool_id=tool_id,
        )

        if self.config.include_tool_inputs:
            # Safely serialize tool input
            try:
                event.tool_input = tool_input if isinstance(tool_input, dict) else {"value": str(tool_input)}
            except Exception:
                event.tool_input = {"error": "Could not serialize input"}

        self._add_event(event)

    def _handle_tool_result(self, block: Any) -> None:
        """Handle a tool result block."""
        # Get tool_use_id from block to correlate with pending tool
        tool_use_id = getattr(block, 'tool_use_id', None)

        # Look up pending tool info
        pending = self._pending_tools.pop(tool_use_id, None) if tool_use_id else None

        if pending:
            tool_name = pending["name"]
            tool_id = tool_use_id
            duration_ms = int((time.time() - pending["start_time"]) * 1000)
        else:
            # Fallback if we can't correlate
            tool_name = "unknown"
            tool_id = tool_use_id
            duration_ms = 0

        # Determine success/failure
        is_error = getattr(block, 'is_error', False) or getattr(block, 'is_error', None)
        success = not is_error

        # Get output - handle string, list of dicts, list of objects, or None
        output = ""
        content = getattr(block, 'content', None)

        if content is None:
            output = ""
        elif isinstance(content, str):
            output = content
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and 'text' in item:
                    # List of dicts with 'text' key
                    output += item['text']
                elif hasattr(item, 'text'):
                    # List of objects with .text attribute
                    output += item.text

        # Update tool stats
        stats = self._tool_stats[tool_name]
        stats["count"] += 1
        stats["duration_ms"] += duration_ms
        if success:
            stats["success"] += 1
        else:
            stats["failure"] += 1

        event = RunEvent(
            type=EventType.TOOL_RESULT,
            tool_name=tool_name,
            tool_id=tool_id,
            tool_duration_ms=duration_ms,
            tool_success=success,
        )

        if self.config.include_tool_outputs:
            event.tool_output = self._truncate(output)

        self._add_event(event)

    def _handle_result(self, message: Any) -> None:
        """Handle the final result message - this contains all the usage info."""
        result_text = getattr(message, 'result', '')

        # Extract timing from SDK (more accurate than our measurement)
        sdk_duration = getattr(message, 'duration_ms', None)
        if sdk_duration is not None:
            self.run.duration_ms = sdk_duration

        self.run.api_duration_ms = getattr(message, 'duration_api_ms', None)
        self.run.num_turns = getattr(message, 'num_turns', None)
        self.run.sdk_cost_usd = getattr(message, 'total_cost_usd', None)
        self.run.sdk_session_id = getattr(message, 'session_id', None)

        # Check for error flag
        if getattr(message, 'is_error', False) and not self.run.error:
            self.run.error = ErrorInfo(
                type="SDKError",
                message="Run completed with error flag set",
            )

        # Extract token usage (only exists on ResultMessage)
        self._extract_usage(message)

        self._add_event(RunEvent(
            type=EventType.RUN_END,
            content=self._truncate(str(result_text)) if result_text else None,
        ))

    def _extract_usage(self, message: Any) -> None:
        """Extract token usage from a message if available."""
        usage = None

        # Try different attribute names
        if hasattr(message, 'usage'):
            usage = message.usage
        elif hasattr(message, 'token_usage'):
            usage = message.token_usage

        if usage:
            if hasattr(usage, 'input_tokens'):
                self.run.tokens.input += getattr(usage, 'input_tokens', 0)
                self.run.tokens.output += getattr(usage, 'output_tokens', 0)
                self.run.tokens.cache_read += getattr(usage, 'cache_read_input_tokens', 0)
                self.run.tokens.cache_write += getattr(usage, 'cache_creation_input_tokens', 0)
            elif isinstance(usage, dict):
                self.run.tokens.input += usage.get('input_tokens', 0)
                self.run.tokens.output += usage.get('output_tokens', 0)
                self.run.tokens.cache_read += usage.get('cache_read_input_tokens', 0)
                self.run.tokens.cache_write += usage.get('cache_creation_input_tokens', 0)

    def record_error(self, error: Exception) -> None:
        """Record an error that occurred during the run."""
        self.run.error = ErrorInfo(
            type=type(error).__name__,
            message=str(error),
            stack=None,  # Could add traceback if desired
        )

        self._add_event(RunEvent(
            type=EventType.ERROR,
            error=self.run.error,
        ))

    def finish(self, status: Optional[RunStatus] = None) -> AgentRun:
        """
        Mark the run as finished and compute final metrics.

        Call this after processing all messages.
        """
        self.run.finished_at = datetime.now(timezone.utc).isoformat() + "Z"
        self.run.duration_ms = int((time.time() - self._start_time) * 1000)

        # Determine status
        if status:
            self.run.status = status
        elif self.run.error:
            self.run.status = RunStatus.FAILED
        else:
            self.run.status = RunStatus.COMPLETED

        # Only compute cost estimate if SDK didn't provide one
        if self.run.sdk_cost_usd is None:
            self.run.estimated_cost_usd = estimate_cost(self.run.tokens, self.run.model)

        # Compile tool summaries
        self.run.tool_calls = [
            ToolCallSummary(
                tool=tool_name,
                count=stats["count"],
                total_duration_ms=stats["duration_ms"],
                success_count=stats["success"],
                failure_count=stats["failure"],
            )
            for tool_name, stats in self._tool_stats.items()
        ]

        return self.run

    async def ship(self) -> bool:
        """
        Ship the completed run to the configured destination.

        Returns True if successful, False otherwise.
        """
        if self.config.mode == OutputMode.DISABLED:
            return True

        if self.config.mode == OutputMode.CONSOLE:
            self._print_summary()
            return True

        if self.config.mode == OutputMode.HTTP:
            return await send_run(self.run, self.config)

        return False

    def _print_summary(self) -> None:
        """Print a summary to console."""
        run = self.run

        print("\n" + "=" * 60)
        print("📊 AGENT RUN SUMMARY")
        print("=" * 60)

        # Basic info
        print(f"Run ID:     {run.run_id}")
        if run.agent_id:
            print(f"Agent:      {run.agent_id}")
        print(f"Status:     {run.status.value}")

        # Duration breakdown
        duration_parts = [f"{run.duration_ms}ms"]
        if run.api_duration_ms is not None:
            overhead = run.duration_ms - run.api_duration_ms if run.duration_ms else 0
            duration_parts.append(f"API: {run.api_duration_ms}ms")
            if overhead > 0:
                duration_parts.append(f"Overhead: {overhead}ms")
        print(f"Duration:   {', '.join(duration_parts)}")

        # Time to first token
        if run.first_token_ms is not None:
            print(f"TTFT:       {run.first_token_ms}ms")

        if run.num_turns:
            print(f"Turns:      {run.num_turns}")

        # Model & Tokens
        if run.model:
            print(f"Model:      {run.model}")

        # Token breakdown with cache info
        token_str = f"{run.tokens.input:,} in / {run.tokens.output:,} out"
        if run.tokens.cache_read > 0 or run.tokens.cache_write > 0:
            cache_parts = []
            if run.tokens.cache_read > 0:
                cache_parts.append(f"{run.tokens.cache_read:,} read")
            if run.tokens.cache_write > 0:
                cache_parts.append(f"{run.tokens.cache_write:,} write")
            token_str += f" (cache: {', '.join(cache_parts)})"
        print(f"Tokens:     {token_str}")

        # Cost - prefer SDK cost (more accurate) over our estimate
        if run.sdk_cost_usd is not None:
            print(f"Cost:       ${run.sdk_cost_usd:.4f} (SDK)")
        elif run.estimated_cost_usd:
            print(f"Est. Cost:  ${run.estimated_cost_usd:.4f}")

        # Trace context (useful for correlation)
        print(f"Trace:      {run.trace_id[:16]}...")

        # Tool usage
        if run.tool_calls:
            print("\n📦 Tool Usage:")
            for tc in run.tool_calls:
                status = "✓" if tc.failure_count == 0 else f"✓{tc.success_count}/✗{tc.failure_count}"
                print(f"  • {tc.tool}: {tc.count}x ({tc.total_duration_ms}ms) [{status}]")

        # Event breakdown (if trace is enabled)
        if run.events:
            thinking_count = sum(1 for e in run.events if e.type == EventType.THINKING)
            stream_count = sum(1 for e in run.events if e.type == EventType.STREAM_EVENT)
            user_msg_count = sum(1 for e in run.events if e.type == EventType.USER_MESSAGE)

            if thinking_count or stream_count or user_msg_count:
                print("\n📋 Event Breakdown:")
                if thinking_count:
                    print(f"  • Thinking blocks: {thinking_count}")
                if stream_count:
                    print(f"  • Stream events: {stream_count}")
                if user_msg_count:
                    print(f"  • User messages: {user_msg_count}")

        # Error if any
        if run.error:
            print(f"\n❌ Error: {run.error.type}: {run.error.message}")

        print("=" * 60 + "\n")

    def get_run(self) -> AgentRun:
        """Get the current run data."""
        return self.run