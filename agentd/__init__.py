# Public exports
from .client import query, tracked_query, track_run
from .tracker import AgentTracker
from .config import configure, get_config, AgentDConfig, OutputMode
from .transport import close_session
from .models import (
    AgentRun,
    RunStatus,
    RunEvent,
    EventType,
    TokenUsage,
    ToolCallSummary,
    ErrorInfo,
)

__all__ = [
    # Main entry points
    "query",
    "tracked_query",
    "track_run",
    # Configuration
    "configure",
    "get_config",
    "AgentDConfig",
    "OutputMode",
    # Transport
    "close_session",
    # Core classes
    "AgentTracker",
    # Data models
    "AgentRun",
    "RunStatus",
    "RunEvent",
    "EventType",
    "TokenUsage",
    "ToolCallSummary",
    "ErrorInfo",
]

__version__ = "0.1.0"
