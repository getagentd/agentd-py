"""
Basic usage example - Drop-in replacement for claude_agent_sdk.query()

This is the simplest way to use agentd. Just replace your import
and get automatic metrics tracking.
"""

import asyncio

# Before: from claude_agent_sdk import query
# After:
from agentd import query, AgentDConfig


async def main():
    """Simple example showing drop-in replacement."""

    # Use query() exactly like you would use claude_agent_sdk.query()
    # Metrics are collected automatically
    async for message in query(
        prompt="What is the capital of France?",
        agent_id="basic-example",  # Optional: helps identify this agent in dashboards
    ):
        # Process messages as normal
        message_type = type(message).__name__

        if message_type == "AssistantMessage":
            # Handle assistant responses
            if hasattr(message, 'content'):
                for block in message.content:
                    if hasattr(block, 'text'):
                        print(f"Assistant: {block.text}")

        elif message_type == "ResultMessage":
            # Final result
            print(f"\nResult: {message.result}")

    # Metrics are automatically shipped when the query completes
    # By default, a summary is printed to console


async def with_options():
    """Example with ClaudeAgentOptions."""

    # If you use options, they work exactly the same
    try:
        from claude_agent_sdk import ClaudeAgentOptions

        options = ClaudeAgentOptions(
            model="claude-sonnet-4-5-20250929",
        )

        async for message in query(
            prompt="Explain Python async/await in one paragraph.",
            options=options,
            agent_id="options-example",
            metadata={"task": "explanation", "topic": "async"},
        ):
            message_type = type(message).__name__
            if message_type == "ResultMessage":
                print(f"Result: {message.result}")

    except ImportError:
        print("claude_agent_sdk not installed - this is just a demo")


if __name__ == "__main__":
    asyncio.run(main())