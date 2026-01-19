"""
Reference Receiver Implementation

A minimal, self-hostable receiver for AgentMetrics data.
Uses SQLite for storage and FastAPI for the API.

Run with:
    pip install fastapi uvicorn pydantic-settings
    uvicorn receiver:app --reload --port 8080

Configuration via environment variables:
    AGENTMETRICS_DB_PATH=./agentmetrics.db
    AGENTMETRICS_API_KEY=your-secret-key  # Optional
    AGENTMETRICS_CORS_ORIGINS=*
    AGENTMETRICS_LOG_LEVEL=INFO
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from asyncio import get_event_loop
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from enum import Enum
from functools import partial
from pathlib import Path
from queue import Queue, Empty
from threading import Lock
from typing import Any, Callable, Optional, TypeVar

try:
    from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel, Field
except ImportError:
    raise ImportError(
        "FastAPI and Pydantic are required. Install with: pip install fastapi uvicorn pydantic-settings"
    )

T = TypeVar("T")

# ============================================================================
# Configuration
# ============================================================================

RECEIVER_VERSION = "0.2.0"
API_VERSION = "v1"


class Settings:
    """Configuration from environment variables."""

    def __init__(self):
        self.db_path = Path(os.getenv("AGENTMETRICS_DB_PATH", "agentmetrics.db"))
        self.api_key = os.getenv("AGENTMETRICS_API_KEY")  # None = no auth required
        self.cors_origins = os.getenv("AGENTMETRICS_CORS_ORIGINS", "*").split(",")
        self.log_level = os.getenv("AGENTMETRICS_LOG_LEVEL", "INFO")
        self.max_payload_bytes = int(os.getenv("AGENTMETRICS_MAX_PAYLOAD_BYTES", 10_000_000))
        self.max_events_per_run = int(os.getenv("AGENTMETRICS_MAX_EVENTS_PER_RUN", 10_000))
        self.db_pool_size = int(os.getenv("AGENTMETRICS_DB_POOL_SIZE", 5))
        self.db_pool_timeout = float(os.getenv("AGENTMETRICS_DB_POOL_TIMEOUT", 30.0))


settings = Settings()

# ============================================================================
# Logging
# ============================================================================

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("agentmetrics.receiver")


# ============================================================================
# Pydantic Models
# ============================================================================

class RunStatus(str, Enum):
    running = "running"
    completed = "completed"
    failed = "failed"
    timeout = "timeout"


class EventType(str, Enum):
    run_start = "run_start"
    assistant_message = "assistant_message"
    thinking = "thinking"
    tool_call = "tool_call"
    tool_result = "tool_result"
    error = "error"
    api_error = "api_error"
    run_end = "run_end"
    stream_event = "stream_event"
    system_message = "system_message"
    user_message = "user_message"


class TokenUsage(BaseModel):
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0


class ErrorInfo(BaseModel):
    type: str
    message: str
    stack: Optional[str] = None


class ToolCallSummary(BaseModel):
    tool: str
    count: int = 0
    total_duration_ms: int = 0
    success_count: int = 0
    failure_count: int = 0


class RunEvent(BaseModel):
    event_id: str
    type: EventType
    timestamp: str
    sequence_number: int = 0
    tool_name: Optional[str] = None
    tool_id: Optional[str] = None
    tool_input: Optional[dict] = None
    tool_output: Optional[str] = None
    tool_duration_ms: Optional[int] = None
    tool_success: Optional[bool] = None
    content: Optional[str] = None
    thinking: Optional[str] = None
    tokens: Optional[TokenUsage] = None
    error: Optional[ErrorInfo] = None


class AgentRun(BaseModel):
    run_id: str
    agent_id: Optional[str] = None
    session_id: Optional[str] = None
    sdk_session_id: Optional[str] = None
    started_at: str
    finished_at: Optional[str] = None
    duration_ms: Optional[int] = None
    api_duration_ms: Optional[int] = None
    first_token_ms: Optional[int] = None
    num_turns: Optional[int] = None
    status: RunStatus = RunStatus.running
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    cost_usd: Optional[float] = None
    cost_source: Optional[str] = None
    sdk_cost_usd: Optional[float] = None
    estimated_cost_usd: Optional[float] = None
    model: Optional[str] = None
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    error: Optional[ErrorInfo] = None
    tool_calls: list[ToolCallSummary] = Field(default_factory=list)
    events: list[RunEvent] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    prompt: Optional[str] = None


class IngestResponse(BaseModel):
    status: str = "accepted"
    run_id: Optional[str] = None


class PaginatedResponse(BaseModel):
    data: list[Any]
    total: int
    limit: int
    offset: int
    has_more: bool


class HealthResponse(BaseModel):
    status: str
    timestamp: str
    version: str
    db_size_bytes: Optional[int] = None
    db_pool_size: int = 0
    db_pool_available: int = 0


class Capabilities(BaseModel):
    version: str
    api_version: str
    features: dict[str, Any]
    limits: dict[str, Any]


class AggregateStats(BaseModel):
    total_runs: int
    completed: int
    failed: int
    avg_duration_ms: Optional[float]
    avg_api_duration_ms: Optional[float]
    avg_first_token_ms: Optional[float]
    avg_num_turns: Optional[float]
    total_tokens_input: int
    total_tokens_output: int
    total_cache_read: int
    total_cache_write: int
    total_cost_usd: Optional[float]
    total_sdk_cost_usd: Optional[float]
    total_estimated_cost_usd: Optional[float]


class AgentStats(BaseModel):
    agent_id: str
    run_count: int
    success_count: int
    failure_count: int
    avg_duration_ms: Optional[float]
    total_cost_usd: Optional[float]
    last_run_at: Optional[str]


class ToolStats(BaseModel):
    tool_name: str
    call_count: int
    success_count: int
    failure_count: int
    avg_duration_ms: Optional[float]


# ============================================================================
# Database Connection Pool
# ============================================================================

class ConnectionPool:
    """
    Thread-safe SQLite connection pool.

    SQLite connections can be shared across threads with check_same_thread=False,
    but we use a pool to limit concurrent connections and reuse them efficiently.
    """

    def __init__(self, db_path: Path, pool_size: int = 5, timeout: float = 30.0):
        self.db_path = db_path
        self.pool_size = pool_size
        self.timeout = timeout
        self._pool: Queue[sqlite3.Connection] = Queue(maxsize=pool_size)
        self._lock = Lock()
        self._initialized = False
        self._executor = ThreadPoolExecutor(max_workers=pool_size, thread_name_prefix="db")

    def _create_connection(self) -> sqlite3.Connection:
        """Create a new database connection with optimized settings."""
        conn = sqlite3.connect(
            self.db_path,
            timeout=self.timeout,
            check_same_thread=False,  # Allow sharing across threads
        )
        conn.row_factory = sqlite3.Row
        # SQLite optimizations
        conn.execute("PRAGMA journal_mode=WAL")  # Write-Ahead Logging for concurrency
        conn.execute("PRAGMA synchronous=NORMAL")  # Balance safety and speed
        conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
        conn.execute("PRAGMA temp_store=MEMORY")  # Store temp tables in memory
        conn.execute("PRAGMA mmap_size=268435456")  # 256MB memory-mapped I/O
        return conn

    def initialize(self):
        """Pre-populate the pool with connections."""
        with self._lock:
            if self._initialized:
                return
            for _ in range(self.pool_size):
                self._pool.put(self._create_connection())
            self._initialized = True
            logger.info(f"Connection pool initialized with {self.pool_size} connections")

    @contextmanager
    def connection(self):
        """Get a connection from the pool (context manager)."""
        conn = None
        try:
            conn = self._pool.get(timeout=self.timeout)
            yield conn
        except Empty:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database connection pool exhausted",
            )
        finally:
            if conn is not None:
                try:
                    conn.rollback()  # Reset any uncommitted state
                except Exception:
                    pass
                self._pool.put(conn)

    async def execute(self, func: Callable[..., T], *args, **kwargs) -> T:
        """Execute a database function in the thread pool (non-blocking)."""
        loop = get_event_loop()
        return await loop.run_in_executor(
            self._executor,
            partial(func, *args, **kwargs),
        )

    def close(self):
        """Close all connections in the pool."""
        with self._lock:
            while not self._pool.empty():
                try:
                    conn = self._pool.get_nowait()
                    conn.close()
                except Empty:
                    break
            self._executor.shutdown(wait=False)
            self._initialized = False
            logger.info("Connection pool closed")


# Global connection pool
db_pool: Optional[ConnectionPool] = None


def get_db_pool() -> ConnectionPool:
    """Get the global connection pool."""
    global db_pool
    if db_pool is None:
        db_pool = ConnectionPool(
            settings.db_path,
            pool_size=settings.db_pool_size,
            timeout=settings.db_pool_timeout,
        )
    return db_pool


@contextmanager
def get_db():
    """Get a database connection from the pool."""
    with get_db_pool().connection() as conn:
        yield conn


def init_db():
    """Initialize database tables."""
    pool = get_db_pool()
    pool.initialize()

    with pool.connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                agent_id TEXT,
                session_id TEXT,
                status TEXT NOT NULL DEFAULT 'running',
                started_at TEXT NOT NULL,
                finished_at TEXT,
                duration_ms INTEGER,
                api_duration_ms INTEGER,
                first_token_ms INTEGER,
                num_turns INTEGER,
                tokens_input INTEGER DEFAULT 0,
                tokens_output INTEGER DEFAULT 0,
                tokens_cache_read INTEGER DEFAULT 0,
                tokens_cache_write INTEGER DEFAULT 0,
                cost_usd REAL,
                cost_source TEXT,
                estimated_cost_usd REAL,
                sdk_cost_usd REAL,
                model TEXT,
                trace_id TEXT NOT NULL,
                span_id TEXT NOT NULL,
                parent_span_id TEXT,
                error_type TEXT,
                error_message TEXT,
                data JSON NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_runs_agent_id ON runs(agent_id);
            CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs(started_at DESC);
            CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
            CREATE INDEX IF NOT EXISTS idx_runs_trace_id ON runs(trace_id);
            CREATE INDEX IF NOT EXISTS idx_runs_model ON runs(model);

            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                sequence_number INTEGER DEFAULT 0,
                tool_name TEXT,
                tool_duration_ms INTEGER,
                tool_success INTEGER,
                data JSON NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_events_run_id ON events(run_id);
            CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
            CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
        """)

    logger.info(f"Database initialized at {settings.db_path}")


# ============================================================================
# Dependencies
# ============================================================================

async def verify_api_key(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Verify API key if configured."""
    if not settings.api_key:
        return  # No auth required

    # Check Authorization header (Bearer token)
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        if token == settings.api_key:
            return

    # Check X-API-Key header
    if x_api_key == settings.api_key:
        return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API key",
        headers={"WWW-Authenticate": "Bearer"},
    )


# ============================================================================
# Middleware
# ============================================================================

class RequestTimingMiddleware:
    """Add request timing headers."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start_time = time.perf_counter()

        async def send_with_timing(message):
            if message["type"] == "http.response.start":
                duration_ms = (time.perf_counter() - start_time) * 1000
                headers = list(message.get("headers", []))
                headers.append((b"x-response-time-ms", str(round(duration_ms, 2)).encode()))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_timing)


# ============================================================================
# App Lifespan
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup
    init_db()
    logger.info(f"AgentMetrics Receiver v{RECEIVER_VERSION} started")
    yield
    # Shutdown
    pool = get_db_pool()
    pool.close()
    logger.info("AgentMetrics Receiver shutting down")


# ============================================================================
# FastAPI App
# ============================================================================

app = FastAPI(
    title="AgentMetrics Receiver",
    description="Reference implementation for receiving agent metrics and traces",
    version=RECEIVER_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Middleware
app.add_middleware(RequestTimingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Response-Time-Ms"],
)


# ============================================================================
# Exception Handlers
# ============================================================================

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """Handle unexpected exceptions."""
    logger.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error", "type": type(exc).__name__},
    )


# ============================================================================
# Ingest Endpoints
# ============================================================================

@app.post(
    "/v1/runs",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=IngestResponse,
    tags=["Ingest"],
    dependencies=[Depends(verify_api_key)],
)
async def ingest_run(run: AgentRun):
    """
    Ingest a completed agent run.

    This is the main endpoint the SDK calls after a run completes.
    Use run_id for idempotency - duplicate submissions update existing records.
    """
    with get_db() as conn:
        try:
            error = run.error
            tokens = run.tokens

            conn.execute("""
                INSERT OR REPLACE INTO runs (
                    run_id, agent_id, session_id, status,
                    started_at, finished_at, duration_ms,
                    api_duration_ms, first_token_ms, num_turns,
                    tokens_input, tokens_output, tokens_cache_read, tokens_cache_write,
                    cost_usd, cost_source, estimated_cost_usd, sdk_cost_usd,
                    model, trace_id, span_id, parent_span_id,
                    error_type, error_message, data
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run.run_id,
                run.agent_id,
                run.session_id,
                run.status.value,
                run.started_at,
                run.finished_at,
                run.duration_ms,
                run.api_duration_ms,
                run.first_token_ms,
                run.num_turns,
                tokens.input,
                tokens.output,
                tokens.cache_read,
                tokens.cache_write,
                run.cost_usd,
                run.cost_source,
                run.estimated_cost_usd,
                run.sdk_cost_usd,
                run.model,
                run.trace_id,
                run.span_id,
                run.parent_span_id,
                error.type if error else None,
                error.message if error else None,
                run.model_dump_json(),
            ))

            # Store events
            for event in run.events:
                conn.execute("""
                    INSERT OR REPLACE INTO events (
                        event_id, run_id, type, timestamp, sequence_number,
                        tool_name, tool_duration_ms, tool_success, data
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    event.event_id,
                    run.run_id,
                    event.type.value,
                    event.timestamp,
                    event.sequence_number,
                    event.tool_name,
                    event.tool_duration_ms,
                    1 if event.tool_success else 0 if event.tool_success is False else None,
                    event.model_dump_json(),
                ))

            conn.commit()
            logger.debug(f"Ingested run {run.run_id} with {len(run.events)} events")
            return IngestResponse(run_id=run.run_id)

        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to ingest run {run.run_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error: {str(e)}",
            )


@app.post(
    "/v1/runs/{run_id}/events",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=IngestResponse,
    tags=["Ingest"],
    dependencies=[Depends(verify_api_key)],
)
async def ingest_event(run_id: str, event: RunEvent):
    """
    Ingest a single event (for streaming mode).

    Use event_id for idempotency.
    """
    with get_db() as conn:
        try:
            conn.execute("""
                INSERT OR REPLACE INTO events (
                    event_id, run_id, type, timestamp, sequence_number,
                    tool_name, tool_duration_ms, tool_success, data
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event.event_id,
                run_id,
                event.type.value,
                event.timestamp,
                event.sequence_number,
                event.tool_name,
                event.tool_duration_ms,
                1 if event.tool_success else 0 if event.tool_success is False else None,
                event.model_dump_json(),
            ))
            conn.commit()
            return IngestResponse()

        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to ingest event {event.event_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error: {str(e)}",
            )


# ============================================================================
# Query Endpoints
# ============================================================================

@app.get(
    "/v1/runs",
    response_model=PaginatedResponse,
    tags=["Query"],
    dependencies=[Depends(verify_api_key)],
)
async def list_runs(
    agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
    status: Optional[RunStatus] = Query(None, description="Filter by status"),
    model: Optional[str] = Query(None, description="Filter by model"),
    trace_id: Optional[str] = Query(None, description="Filter by trace ID"),
    limit: int = Query(50, ge=1, le=1000, description="Max results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
):
    """List runs with optional filters and pagination."""
    with get_db() as conn:
        # Build query
        conditions = ["1=1"]
        params: list = []

        if agent_id:
            conditions.append("agent_id = ?")
            params.append(agent_id)
        if status:
            conditions.append("status = ?")
            params.append(status.value)
        if model:
            conditions.append("model = ?")
            params.append(model)
        if trace_id:
            conditions.append("trace_id = ?")
            params.append(trace_id)

        where_clause = " AND ".join(conditions)

        # Get total count
        total = conn.execute(
            f"SELECT COUNT(*) FROM runs WHERE {where_clause}", params
        ).fetchone()[0]

        # Get paginated results
        rows = conn.execute(
            f"SELECT data FROM runs WHERE {where_clause} ORDER BY started_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()

        return PaginatedResponse(
            data=[json.loads(row["data"]) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
            has_more=(offset + limit) < total,
        )


@app.get(
    "/v1/runs/{run_id}",
    tags=["Query"],
    dependencies=[Depends(verify_api_key)],
)
async def get_run(run_id: str):
    """Get a single run by ID."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT data FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()

        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Run {run_id} not found",
            )

        return json.loads(row["data"])


@app.get(
    "/v1/runs/{run_id}/events",
    response_model=list[dict],
    tags=["Query"],
    dependencies=[Depends(verify_api_key)],
)
async def get_run_events(run_id: str):
    """Get all events for a run, ordered by sequence number."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT data FROM events WHERE run_id = ? ORDER BY sequence_number, timestamp",
            (run_id,),
        ).fetchall()

        return [json.loads(row["data"]) for row in rows]


@app.get(
    "/v1/traces/{trace_id}",
    tags=["Query"],
    dependencies=[Depends(verify_api_key)],
)
async def get_trace(trace_id: str):
    """Get all runs for a trace (for distributed tracing)."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT data FROM runs WHERE trace_id = ? ORDER BY started_at",
            (trace_id,),
        ).fetchall()

        if not rows:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Trace {trace_id} not found",
            )

        return [json.loads(row["data"]) for row in rows]


@app.get(
    "/v1/agents",
    response_model=list[AgentStats],
    tags=["Query"],
    dependencies=[Depends(verify_api_key)],
)
async def list_agents():
    """List all known agents with aggregated statistics."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT
                agent_id,
                COUNT(*) as run_count,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as success_count,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failure_count,
                AVG(duration_ms) as avg_duration_ms,
                SUM(COALESCE(cost_usd, estimated_cost_usd)) as total_cost_usd,
                MAX(started_at) as last_run_at
            FROM runs
            WHERE agent_id IS NOT NULL
            GROUP BY agent_id
            ORDER BY last_run_at DESC
        """).fetchall()

        return [AgentStats(**dict(row)) for row in rows]


@app.get(
    "/v1/stats",
    response_model=AggregateStats,
    tags=["Query"],
    dependencies=[Depends(verify_api_key)],
)
async def get_stats(
    agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
    since: Optional[str] = Query(None, description="Filter runs after this ISO date"),
):
    """Get aggregate statistics."""
    with get_db() as conn:
        conditions = ["1=1"]
        params: list = []

        if agent_id:
            conditions.append("agent_id = ?")
            params.append(agent_id)
        if since:
            conditions.append("started_at >= ?")
            params.append(since)

        where_clause = " AND ".join(conditions)

        row = conn.execute(f"""
            SELECT
                COUNT(*) as total_runs,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                AVG(duration_ms) as avg_duration_ms,
                AVG(api_duration_ms) as avg_api_duration_ms,
                AVG(first_token_ms) as avg_first_token_ms,
                AVG(num_turns) as avg_num_turns,
                COALESCE(SUM(tokens_input), 0) as total_tokens_input,
                COALESCE(SUM(tokens_output), 0) as total_tokens_output,
                COALESCE(SUM(tokens_cache_read), 0) as total_cache_read,
                COALESCE(SUM(tokens_cache_write), 0) as total_cache_write,
                SUM(COALESCE(cost_usd, estimated_cost_usd)) as total_cost_usd,
                SUM(sdk_cost_usd) as total_sdk_cost_usd,
                SUM(estimated_cost_usd) as total_estimated_cost_usd
            FROM runs
            WHERE {where_clause}
        """, params).fetchone()

        return AggregateStats(**dict(row))


@app.get(
    "/v1/tools",
    response_model=list[ToolStats],
    tags=["Query"],
    dependencies=[Depends(verify_api_key)],
)
async def get_tool_stats(
    agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
    since: Optional[str] = Query(None, description="Filter runs after this ISO date"),
):
    """Get tool usage statistics."""
    with get_db() as conn:
        conditions = ["e.tool_name IS NOT NULL"]
        params: list = []

        if agent_id:
            conditions.append("r.agent_id = ?")
            params.append(agent_id)
        if since:
            conditions.append("r.started_at >= ?")
            params.append(since)

        where_clause = " AND ".join(conditions)

        rows = conn.execute(f"""
            SELECT
                e.tool_name,
                COUNT(*) as call_count,
                SUM(CASE WHEN e.tool_success = 1 THEN 1 ELSE 0 END) as success_count,
                SUM(CASE WHEN e.tool_success = 0 THEN 1 ELSE 0 END) as failure_count,
                AVG(e.tool_duration_ms) as avg_duration_ms
            FROM events e
            JOIN runs r ON e.run_id = r.run_id
            WHERE {where_clause}
            GROUP BY e.tool_name
            ORDER BY call_count DESC
        """, params).fetchall()

        return [ToolStats(**dict(row)) for row in rows]


# ============================================================================
# System Endpoints
# ============================================================================

@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health():
    """Health check endpoint with database and pool status."""
    db_size = None
    try:
        if settings.db_path.exists():
            db_size = settings.db_path.stat().st_size
    except Exception:
        pass

    pool = get_db_pool()
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now(timezone.utc).isoformat(),
        version=RECEIVER_VERSION,
        db_size_bytes=db_size,
        db_pool_size=pool.pool_size,
        db_pool_available=pool._pool.qsize(),
    )


@app.get("/v1/capabilities", response_model=Capabilities, tags=["System"])
async def get_capabilities():
    """
    Return receiver capabilities for SDK feature negotiation.

    Enables graceful degradation with older receivers.
    """
    return Capabilities(
        version=RECEIVER_VERSION,
        api_version=API_VERSION,
        features={
            "streaming_events": True,
            "batch_ingest": False,
            "compression": [],
            "authentication": settings.api_key is not None,
            "trace_queries": True,
        },
        limits={
            "max_events_per_run": settings.max_events_per_run,
            "max_payload_bytes": settings.max_payload_bytes,
            "retention_days": None,
        },
    )


# ============================================================================
# Admin Endpoints
# ============================================================================

@app.delete(
    "/v1/runs/{run_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Admin"],
    dependencies=[Depends(verify_api_key)],
)
async def delete_run(run_id: str):
    """Delete a run and its events."""
    with get_db() as conn:
        # Check if exists
        row = conn.execute(
            "SELECT run_id FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()

        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Run {run_id} not found",
            )

        # Delete (events cascade)
        conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
        conn.commit()
        logger.info(f"Deleted run {run_id}")


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "receiver:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8080)),
        reload=os.getenv("ENV", "development") == "development",
        log_level=settings.log_level.lower(),
    )
