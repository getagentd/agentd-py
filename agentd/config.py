# Configuration management
"""
Configuration for AgentD.

Configure via:
1. Environment variables (recommended for production)
2. Global configure() call
3. Per-query config override
"""
from __future__ import annotations

import os

# Version info
SDK_VERSION = "0.1.0"
API_VERSION = "v1"
MIN_RECEIVER_VERSION = "0.1.0"
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Any


class OutputMode(str, Enum):
    """How to output metrics."""
    CONSOLE = "console"  # Print summary to stdout
    HTTP = "http"        # Ship to HTTP endpoint
    DISABLED = "disabled"  # No output


@dataclass
class AgentDConfig:
    """Configuration for AgentD."""

    # Output mode
    mode: OutputMode = OutputMode.CONSOLE

    # HTTP endpoint (when mode=HTTP)
    endpoint_url: Optional[str] = None
    api_key: Optional[str] = None

    # Default identifiers
    agent_id: Optional[str] = None
    session_id: Optional[str] = None

    # What to include in traces
    include_trace: bool = True
    include_prompt: bool = False
    include_tool_inputs: bool = True
    include_tool_outputs: bool = True

    # Truncation
    truncate_outputs_at: int = 10000

    # Default metadata
    default_metadata: dict[str, Any] = field(default_factory=dict)

    # Streaming mode (send events in real-time)
    streaming: bool = False

    # Disabled flag
    disabled: bool = False

    def __post_init__(self):
        # Determine mode from settings
        if self.disabled:
            self.mode = OutputMode.DISABLED
        elif self.endpoint_url:
            self.mode = OutputMode.HTTP
        else:
            self.mode = OutputMode.CONSOLE


# Global config instance
_global_config: Optional[AgentDConfig] = None


def configure(
    *,
    endpoint_url: Optional[str] = None,
    api_key: Optional[str] = None,
    agent_id: Optional[str] = None,
    session_id: Optional[str] = None,
    include_trace: bool = True,
    include_prompt: bool = False,
    include_tool_inputs: bool = True,
    include_tool_outputs: bool = True,
    truncate_outputs_at: int = 10000,
    default_metadata: Optional[dict[str, Any]] = None,
    streaming: Optional[bool] = None,
    disabled: Optional[bool] = None,
) -> AgentDConfig:
    """
    Configure AgentD globally.

    Call this once at application startup. Environment variables are used
    as defaults for endpoint_url, api_key, agent_id, streaming, and disabled.

    Args:
        endpoint_url: HTTP endpoint to ship metrics to (default: AGENTD_URL env var)
        api_key: API key for authentication (default: AGENTD_API_KEY env var)
        agent_id: Default agent ID for all queries (default: AGENTD_AGENT_ID env var)
        session_id: Default session ID for all queries
        include_trace: Include full trace with events
        include_prompt: Include original prompt in traces
        include_tool_inputs: Include tool inputs in traces
        include_tool_outputs: Include tool outputs in traces
        truncate_outputs_at: Max length for outputs before truncation
        default_metadata: Default metadata attached to all runs
        streaming: Enable real-time event streaming (default: AGENTD_STREAMING env var)
        disabled: Disable metrics entirely (default: AGENTD_DISABLED env var)

    Returns:
        The configured AgentDConfig
    """
    global _global_config

    # Use environment variables as defaults
    _endpoint_url = endpoint_url if endpoint_url is not None else os.environ.get("AGENTD_URL")
    _api_key = api_key if api_key is not None else os.environ.get("AGENTD_API_KEY")
    _agent_id = agent_id if agent_id is not None else os.environ.get("AGENTD_AGENT_ID")
    _disabled = disabled if disabled is not None else os.environ.get("AGENTD_DISABLED", "").lower() == "true"
    _streaming = streaming if streaming is not None else os.environ.get("AGENTD_STREAMING", "").lower() == "true"

    _global_config = AgentDConfig(
        endpoint_url=_endpoint_url,
        api_key=_api_key,
        agent_id=_agent_id,
        session_id=session_id,
        include_trace=include_trace,
        include_prompt=include_prompt,
        include_tool_inputs=include_tool_inputs,
        include_tool_outputs=include_tool_outputs,
        truncate_outputs_at=truncate_outputs_at,
        default_metadata=default_metadata or {},
        streaming=_streaming,
        disabled=_disabled,
    )

    return _global_config


def get_config() -> AgentDConfig:
    """
    Get the current configuration.

    If not explicitly configured, reads from environment variables.
    """
    global _global_config

    if _global_config is not None:
        return _global_config

    # Read from environment
    endpoint_url = os.environ.get("AGENTD_URL")
    api_key = os.environ.get("AGENTD_API_KEY")
    agent_id = os.environ.get("AGENTD_AGENT_ID")
    disabled = os.environ.get("AGENTD_DISABLED", "").lower() == "true"
    streaming = os.environ.get("AGENTD_STREAMING", "").lower() == "true"

    _global_config = AgentDConfig(
        endpoint_url=endpoint_url,
        api_key=api_key,
        agent_id=agent_id,
        disabled=disabled,
        streaming=streaming,
    )

    return _global_config


def reset_config() -> None:
    """Reset configuration to default. Mainly for testing."""
    global _global_config
    _global_config = None