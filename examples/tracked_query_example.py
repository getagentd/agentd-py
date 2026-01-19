"""
tracked_query() example - Wrap an existing query iterator

Use this when you want to keep using claude_agent_sdk.query() directly
but still get metrics tracking. This is useful when:

1. You have existing code using claude_agent_sdk.query()
2. You need to access features specific to the SDK's query()
3. You want minimal changes to your codebase
"""

import asyncio

# Keep using the original SDK
try:
    from claude_agent_sdk import query, ClaudeAgentOptions
except ImportError:
    query = None  # For demo purposes

# Import just the tracking wrapper
from agentd import tracked_query


async def main():
    """Wrap an existing query with tracking."""

    if query is None:
        print("Demo mode - claude_agent_sdk not installed")
        return

    options = ClaudeAgentOptions(
        model="claude-sonnet-4-5-20250929",
    )

    # Wrap your existing query() call with tracked_query()
    async for message in tracked_query(
        query(prompt="List 3 programming languages.", options=options),
        agent_id="wrapped-query",
        prompt="List 3 programming languages.",  # Optional: include for debugging
        metadata={"source": "tracked_query_example"},
    ):
        # Process messages exactly as before
        message_type = type(message).__name__

        if message_type == "AssistantMessage":
            if hasattr(message, 'content'):
                for block in message.content:
                    if hasattr(block, 'text'):
                        print(block.text)

    # Metrics are automatically collected and shipped


async def existing_code_pattern():
    """Shows how to add tracking to existing code with minimal changes."""

    if query is None:
        print("Demo mode - claude_agent_sdk not installed")
        return

    # BEFORE: Your existing code
    # async for msg in query(prompt="Hello", options=opts):
    #     handle(msg)

    # AFTER: Just wrap the query() call
    # async for msg in tracked_query(query(prompt="Hello", options=opts), agent_id="x"):
    #     handle(msg)

    # That's it! One line change.
    pass


if __name__ == "__main__":
    asyncio.run(main())