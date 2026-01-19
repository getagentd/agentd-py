"""
Client module - Drop-in replacement for claude_agent_sdk.query()

This provides the main entry points for using AgentD.
"""
from __future__ import annotations

from typing import AsyncIterator, Optional, Any
from contextlib import asynccontextmanager

from .tracker import AgentTracker
from .config import AgentDConfig
from .models import RunStatus


async def query(
        *,
        prompt: str,
        options: Any = None,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        config: Optional[AgentDConfig] = None,
) -> AsyncIterator[Any]:
    """
    Drop-in replacement for claude_agent_sdk.query() with automatic metrics tracking.

    Usage:
        from agentd import query
        # Instead of: from claude_agent_sdk import query

        async for message in query(prompt="...", options=options):
            print(message)

    Args:
        prompt: The prompt to send to Claude
        options: ClaudeAgentOptions (same as claude_agent_sdk)
        agent_id: Identifier for this agent (for grouping in dashboards)
        session_id: Identifier for this session (for grouping related runs)
        metadata: Additional metadata to attach to the run
        config: Override the global AgentDConfig

    Yields:
        Messages from the underlying claude_agent_sdk.query()
    """
    # Import claude_agent_sdk here to avoid hard dependency at import time
    try:
        from claude_agent_sdk import query as sdk_query
    except ImportError:
        raise ImportError(
            "claude_agent_sdk is required. Install it with: pip install claude-agent-sdk"
        )

    # Extract model from options if available
    model = None
    if options and hasattr(options, 'model'):
        model = options.model

    # Create tracker
    tracker = AgentTracker(
        agent_id=agent_id,
        session_id=session_id,
        prompt=prompt,
        metadata=metadata,
        config=config,
    )

    if model:
        tracker.run.model = model

    try:
        # Run the underlying query and track all messages
        async for message in sdk_query(prompt=prompt, options=options):
            tracker.process_message(message)
            yield message

        # Successfully completed
        tracker.finish(RunStatus.COMPLETED)

    except Exception as e:
        # Record the error
        tracker.record_error(e)
        tracker.finish(RunStatus.FAILED)
        raise

    finally:
        # Always ship metrics, even on failure
        await tracker.ship()


async def tracked_query(
        query_iterator: AsyncIterator[Any],
        *,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        prompt: Optional[str] = None,
        metadata: Optional[dict] = None,
        config: Optional[AgentDConfig] = None,
) -> AsyncIterator[Any]:
    """
    Wrap an existing query iterator with tracking.

    Use this when you want to keep using claude_agent_sdk.query() directly
    but still get metrics.

    Usage:
        from claude_agent_sdk import query
        from agentd import tracked_query

        async for message in tracked_query(
            query(prompt="...", options=options),
            agent_id="my-agent"
        ):
            print(message)

    Args:
        query_iterator: The async iterator from claude_agent_sdk.query()
        agent_id: Identifier for this agent
        session_id: Identifier for this session
        prompt: Original prompt (for debugging, optional)
        metadata: Additional metadata
        config: Override the global AgentDConfig

    Yields:
        Messages from the underlying query, unchanged
    """
    tracker = AgentTracker(
        agent_id=agent_id,
        session_id=session_id,
        prompt=prompt,
        metadata=metadata,
        config=config,
    )

    try:
        async for message in query_iterator:
            tracker.process_message(message)
            yield message

        tracker.finish(RunStatus.COMPLETED)

    except Exception as e:
        tracker.record_error(e)
        tracker.finish(RunStatus.FAILED)
        raise

    finally:
        await tracker.ship()


@asynccontextmanager
async def track_run(
        *,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        prompt: Optional[str] = None,
        metadata: Optional[dict] = None,
        config: Optional[AgentDConfig] = None,
):
    """
    Context manager for manual tracking.

    Use this when you need fine-grained control over what gets tracked.

    Usage:
        async with track_run(agent_id="my-agent") as tracker:
            async for message in query(prompt="...", options=options):
                tracker.process_message(message)
                # Do something with message

    Yields:
        AgentTracker instance for manual message processing
    """
    tracker = AgentTracker(
        agent_id=agent_id,
        session_id=session_id,
        prompt=prompt,
        metadata=metadata,
        config=config,
    )

    try:
        yield tracker
        tracker.finish(RunStatus.COMPLETED)
    except Exception as e:
        tracker.record_error(e)
        tracker.finish(RunStatus.FAILED)
        raise
    finally:
        await tracker.ship()