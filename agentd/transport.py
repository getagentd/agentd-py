# HTTP shipping logic
"""
Transport layer for shipping metrics to HTTP endpoints.

Uses connection pooling for efficient HTTP transport.
"""
from __future__ import annotations

import json
import asyncio
import atexit
from typing import Optional, TYPE_CHECKING

from .models import AgentRun, RunEvent
from .config import AgentDConfig

if TYPE_CHECKING:
    import aiohttp

# ============================================================================
# Connection Pool Management
# ============================================================================

_session: Optional[aiohttp.ClientSession] = None
_aiohttp_available: Optional[bool] = None


def _check_aiohttp() -> bool:
    """Check if aiohttp is available."""
    global _aiohttp_available
    if _aiohttp_available is None:
        try:
            import aiohttp
            _aiohttp_available = True
        except ImportError:
            _aiohttp_available = False
    return _aiohttp_available


async def get_session() -> aiohttp.ClientSession:
    """
    Get or create the shared HTTP session with connection pooling.

    The session is lazily initialized on first use and reused across
    all transport calls for efficient connection reuse.
    """
    global _session

    if not _check_aiohttp():
        raise ImportError("aiohttp is required for HTTP transport")

    import aiohttp

    if _session is None or _session.closed:
        connector = aiohttp.TCPConnector(
            limit=20,              # Max total connections
            limit_per_host=10,     # Max connections per host
            keepalive_timeout=30,  # Keep connections alive for reuse
            enable_cleanup_closed=True,
        )
        timeout = aiohttp.ClientTimeout(
            total=30,      # Total request timeout
            connect=10,    # Connection timeout
        )
        _session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
        )

    return _session


async def close_session() -> None:
    """
    Close the shared HTTP session.

    Call this on application shutdown for clean cleanup.
    """
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
        _session = None


def _cleanup_session() -> None:
    """Synchronous cleanup for atexit handler."""
    global _session
    if _session is not None and not _session.closed:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_session.close())
            else:
                loop.run_until_complete(_session.close())
        except Exception:
            pass
        _session = None


# Register cleanup on interpreter shutdown
atexit.register(_cleanup_session)


# ============================================================================
# Transport Functions
# ============================================================================

async def send_run(run: AgentRun, config: AgentDConfig) -> bool:
    """
    Send a completed run to the configured HTTP endpoint.

    Args:
        run: The completed AgentRun to send
        config: Configuration with endpoint URL and API key

    Returns:
        True if successful, False otherwise
    """
    if not config.endpoint_url:
        return False

    if not _check_aiohttp():
        return await _send_run_urllib(run, config)

    runs_url = config.endpoint_url.rstrip("/") + "/v1/runs"

    try:
        session = await get_session()

        headers = {"Content-Type": "application/json"}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"

        async with session.post(
            runs_url,
            json=run.to_dict(),
            headers=headers,
        ) as response:
            return response.status in (200, 201, 202)

    except Exception as e:
        print(f"[agentd] Failed to ship metrics: {e}")
        return False


async def _send_run_urllib(run: AgentRun, config: AgentDConfig) -> bool:
    """Fallback implementation using urllib (no connection pooling)."""
    import urllib.request
    import urllib.error

    runs_url = config.endpoint_url.rstrip("/") + "/v1/runs"

    try:
        data = json.dumps(run.to_dict()).encode("utf-8")

        headers = {"Content-Type": "application/json"}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"

        request = urllib.request.Request(
            runs_url,
            data=data,
            headers=headers,
            method="POST",
        )

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: urllib.request.urlopen(request, timeout=30)
        )

        return response.status in (200, 201, 202)

    except Exception as e:
        print(f"[agentd] Failed to ship metrics: {e}")
        return False


async def send_event(run_id: str, event: RunEvent, config: AgentDConfig) -> bool:
    """
    Send a single event in streaming mode.

    Args:
        run_id: The run ID this event belongs to
        event: The event to send
        config: Configuration with endpoint URL and API key

    Returns:
        True if successful, False otherwise
    """
    if not config.endpoint_url:
        return False

    if not _check_aiohttp():
        return False

    events_url = config.endpoint_url.rstrip("/") + f"/v1/runs/{run_id}/events"

    try:
        import aiohttp
        session = await get_session()

        headers = {"Content-Type": "application/json"}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"

        async with session.post(
            events_url,
            json=event.to_dict(),
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),  # Shorter timeout for streaming
        ) as response:
            return response.status in (200, 201, 202)

    except Exception:
        # Don't log streaming failures to avoid noise
        return False


async def check_capabilities(config: AgentDConfig) -> dict:
    """
    Check receiver capabilities for feature negotiation.

    This is optional and non-blocking. Returns empty dict on failure,
    allowing graceful degradation with older receivers.

    Args:
        config: Configuration with endpoint URL

    Returns:
        Capabilities dict, or empty dict if unavailable
    """
    if not config.endpoint_url:
        return {}

    if not _check_aiohttp():
        return {}

    caps_url = config.endpoint_url.rstrip("/") + "/v1/capabilities"

    try:
        import aiohttp
        session = await get_session()

        async with session.get(
            caps_url,
            timeout=aiohttp.ClientTimeout(total=5),  # Quick timeout
        ) as response:
            if response.status == 200:
                return await response.json()
            return {}

    except Exception:
        # Graceful fallback - don't block if capabilities unavailable
        return {}
