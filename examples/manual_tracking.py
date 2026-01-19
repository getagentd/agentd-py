"""
Manual tracking with track_run() context manager

Use this when you need fine-grained control over what gets tracked.
This is useful when:

1. You want to track only specific messages
2. You need to add custom events or metadata mid-run
3. You're integrating with a complex workflow
4. You want to conditionally process messages before tracking
"""

import asyncio

try:
    from claude_agent_sdk import query, ClaudeAgentOptions
except ImportError:
    query = None

from agentd import track_run


async def main():
    """Fine-grained control with track_run context manager."""

    if query is None:
        print("Demo mode - claude_agent_sdk not installed")
        return

    options = ClaudeAgentOptions(
        model="claude-sonnet-4-5-20250929",
    )

    # Use track_run as a context manager
    async with track_run(
        agent_id="manual-tracking",
        prompt="Write a haiku about code.",
        metadata={"style": "creative"},
    ) as tracker:
        # Run your query
        async for message in query(prompt="Write a haiku about code.", options=options):
            # Manually process each message
            tracker.process_message(message)

            # You can do custom processing here
            message_type = type(message).__name__
            if message_type == "ToolUseBlock":
                print(f"Tool called: {message.name}")
            elif message_type == "AssistantMessage":
                print("Got assistant message")

        # The run is automatically marked as completed when exiting the context
        # Metrics are automatically shipped

    # After the context manager exits, you can access the run data
    # print(f"Run ID: {tracker.run.run_id}")


async def with_error_handling():
    """track_run automatically handles errors."""

    if query is None:
        print("Demo mode - claude_agent_sdk not installed")
        return

    try:
        async with track_run(agent_id="error-example") as tracker:
            # If an error occurs, the run is marked as FAILED
            # and the error is recorded before shipping
            async for message in query(prompt="Do something", options=None):
                tracker.process_message(message)
                # Simulate an error
                raise ValueError("Something went wrong!")

    except ValueError as e:
        # The error is still raised, but metrics are captured
        print(f"Caught error: {e}")
        # The run status will be FAILED with error details


async def selective_tracking():
    """Track only specific message types."""

    if query is None:
        print("Demo mode - claude_agent_sdk not installed")
        return

    async with track_run(agent_id="selective") as tracker:
        async for message in query(prompt="Test", options=None):
            message_type = type(message).__name__

            # Only track tool-related messages
            if message_type in ("ToolUseBlock", "ToolResultBlock"):
                tracker.process_message(message)
            # Skip assistant messages to reduce trace size


async def access_run_data():
    """Access run data during and after execution."""

    if query is None:
        print("Demo mode - claude_agent_sdk not installed")
        return

    async with track_run(agent_id="data-access") as tracker:
        async for message in query(prompt="Hello", options=None):
            tracker.process_message(message)

            # Access current run state
            run = tracker.get_run()
            print(f"Current tokens: {run.tokens.input} in / {run.tokens.output} out")

    # After completion, get final run data
    final_run = tracker.get_run()
    print(f"Final status: {final_run.status}")
    print(f"Total duration: {final_run.duration_ms}ms")
    print(f"Estimated cost: ${final_run.estimated_cost_usd}")


if __name__ == "__main__":
    asyncio.run(main())