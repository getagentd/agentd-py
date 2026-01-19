"""
Configuration example - Customizing agentd behavior

This shows various ways to configure agentd:
1. Environment variables
2. Global configure() call
3. Per-query config override
"""

import asyncio
import os

from agentd import query, configure, track_run
from agentd.config import AgentDConfig, OutputMode


async def environment_variables():
    """
    Configure via environment variables (recommended for production).

    Set these before running your application:

    export AGENTD_URL="https://metrics.yourcompany.com/ingest"
    export AGENTD_API_KEY="your-api-key"
    export AGENTD_AGENT_ID="default-agent-id"
    export AGENTD_DISABLED="false"
    export AGENTD_STREAMING="false"
    """
    # Environment variables are automatically read
    # No code changes needed!
    pass


async def global_configuration():
    """Configure globally with configure()."""

    # Call configure() once at application startup
    configure(
        # HTTP endpoint to ship metrics to (None = console output)
        endpoint_url="https://metrics.yourcompany.com/ingest",

        # API key for authentication
        api_key="your-api-key",

        # Default agent ID for all queries
        agent_id="my-app",

        # Include full trace with events
        include_trace=True,

        # Include the original prompt in traces (disable for privacy)
        include_prompt=False,

        # Include tool inputs/outputs in traces
        include_tool_inputs=True,
        include_tool_outputs=True,

        # Truncate long outputs
        truncate_outputs_at=10000,

        # Default metadata attached to all runs
        default_metadata={
            "environment": "production",
            "version": "1.0.0",
        },

        # Enable real-time event streaming
        streaming=False,
    )

    # Now all queries use this configuration
    async for message in query(prompt="Hello"):
        pass


async def console_mode():
    """Use console mode for local development."""

    # Console mode prints a summary to stdout
    # Great for debugging without setting up an endpoint
    configure(
        endpoint_url=None,  # None = console mode
        include_trace=True,
    )

    async for message in query(prompt="Test", agent_id="dev-test"):
        pass

    # Output:
    # ============================================================
    # AGENT RUN SUMMARY
    # ============================================================
    # Run ID:     550e8400-e29b-41d4-a716-446655440000
    # Agent:      dev-test
    # Status:     completed
    # Duration:   1234ms
    # ...


async def disable_tracking():
    """Disable tracking entirely."""

    # Via environment variable:
    # export AGENTD_DISABLED=true

    # Or via code:
    configure(disabled=True)

    # Queries work normally but no metrics are collected
    async for message in query(prompt="Hello"):
        pass


async def per_query_config():
    """Override configuration for specific queries."""

    # Create a custom config
    custom_config = AgentDConfig(
        mode=OutputMode.CONSOLE,
        include_trace=True,
        include_prompt=True,  # Only for this query
        agent_id="special-query",
    )

    # Pass config to override global settings
    async for message in query(
        prompt="Sensitive query",
        config=custom_config,
    ):
        pass


async def http_endpoint():
    """Ship metrics to an HTTP endpoint."""

    configure(
        endpoint_url="https://ingest.castari.io/v1/runs",
        api_key=os.environ.get("CASTARI_API_KEY"),
        agent_id="my-production-agent",
    )

    # Metrics are automatically POSTed to the endpoint
    async for message in query(prompt="Hello"):
        pass


async def self_hosted():
    """Ship metrics to a self-hosted receiver."""

    # You can run your own metrics receiver
    # The API contract is documented in agentd.models

    configure(
        endpoint_url="http://localhost:8080/api/runs",
        api_key="local-dev-key",
    )

    # See the models.py file for the exact JSON structure sent


async def streaming_mode():
    """Enable real-time event streaming."""

    # Streaming mode sends events as they happen
    # instead of batching at the end
    configure(
        endpoint_url="https://metrics.example.com/events",
        api_key="your-key",
        streaming=True,  # Send events in real-time
    )

    # Each tool call, result, and message is sent immediately
    async for message in query(prompt="Complex task"):
        pass


if __name__ == "__main__":
    # For local development, use console mode
    asyncio.run(console_mode())