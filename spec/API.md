# AgentMetrics API Specification

**Version:** 1.0.0

This document defines the API contract for AgentMetrics receivers. Any implementation that follows this spec will work with the AgentMetrics SDK.

## Overview

The API has two main categories:

1. **Ingest Endpoints** - Receive data from the SDK
2. **Query Endpoints** - Retrieve data for dashboards (optional)

Only the ingest endpoints are required for a minimal receiver.

---

## Authentication

All endpoints accept an optional `Authorization` header:

```
Authorization: Bearer <api_key>
```

Receivers may enforce authentication or ignore it.

---

## Versioning & Compatibility

### Path Versioning

All endpoints are prefixed with `/v1/`. Breaking changes require a new major version (`/v2/`).

### Capability Discovery

The SDK can query `GET /v1/capabilities` to discover receiver features. This enables graceful degradation when connecting to older receivers.

### Compatibility Guarantees

- **Additive changes only**: New fields may be added to responses and requests
- **Clients should ignore unknown fields**: Forward compatibility
- **Fields will not be removed** within a major version
- **Breaking changes require a new API version** (`/v2/`, etc.)

### Version Negotiation

The SDK includes version constants:
- `SDK_VERSION`: Current SDK version (e.g., "0.1.0")
- `API_VERSION`: API version the SDK targets (e.g., "v1")
- `MIN_RECEIVER_VERSION`: Minimum compatible receiver version

Receivers return their version via `/v1/capabilities`. The SDK can use this for feature detection.

---

## Ingest Endpoints

### POST /v1/runs

Receive a completed agent run.

**Request Body:**

```json
{
  "run_id": "uuid-string",
  "agent_id": "string (optional)",
  "session_id": "string (optional)",
  
  "started_at": "2025-01-15T10:30:00Z",
  "finished_at": "2025-01-15T10:30:45Z",
  "duration_ms": 45000,
  
  "status": "completed | failed | timeout",
  
  "error": {
    "type": "string",
    "message": "string",
    "stack": "string (optional)"
  },
  
  "tokens": {
    "input": 15000,
    "output": 3200,
    "cache_read": 0,
    "cache_write": 0
  },
  
  "estimated_cost_usd": 0.12,
  "model": "claude-sonnet-4-5-20250929",
  
  "tool_calls": [
    {
      "tool": "WebSearch",
      "count": 3,
      "total_duration_ms": 1500,
      "success_count": 3,
      "failure_count": 0
    }
  ],
  
  "events": [
    // Array of RunEvent objects (see below)
  ],
  
  "metadata": {
    // Arbitrary key-value pairs
  },
  
  "prompt": "string (optional)"
}
```

**Response:** `202 Accepted`

```json
{
  "status": "accepted",
  "run_id": "uuid-string"
}
```

---

### POST /v1/runs/{run_id}/events

Receive a single event during a run (streaming mode).

**URL Parameters:**
- `run_id`: The run ID this event belongs to

**Request Body:**

```json
{
  "event_id": "uuid-string",
  "type": "run_start | assistant_message | tool_call | tool_result | error | run_end",
  "timestamp": "2025-01-15T10:30:00Z",
  
  // For tool events
  "tool_name": "string (optional)",
  "tool_input": { /* object, optional */ },
  "tool_output": "string (optional)",
  "tool_duration_ms": 450,
  "tool_success": true,
  
  // For message events
  "content": "string (optional)",
  "tokens": { /* TokenUsage object, optional */ },
  
  // For error events
  "error": {
    "type": "string",
    "message": "string"
  }
}
```

**Response:** `202 Accepted`

```json
{
  "status": "accepted"
}
```

---

## Query Endpoints (Optional)

These endpoints are for building dashboards. Implement them if you want query capability.

### GET /v1/runs

List runs with optional filters.

**Query Parameters:**
- `agent_id` (optional): Filter by agent
- `status` (optional): Filter by status
- `limit` (optional, default 50): Max results
- `offset` (optional, default 0): Pagination offset

**Response:** `200 OK`

```json
[
  { /* AgentRun object */ },
  { /* AgentRun object */ }
]
```

---

### GET /v1/runs/{run_id}

Get a single run by ID.

**Response:** `200 OK` with AgentRun object, or `404 Not Found`

---

### GET /v1/runs/{run_id}/events

Get all events for a run.

**Response:** `200 OK`

```json
[
  { /* RunEvent object */ },
  { /* RunEvent object */ }
]
```

---

### GET /v1/agents

List all known agents with statistics.

**Response:** `200 OK`

```json
[
  {
    "agent_id": "my-research-agent",
    "run_count": 150,
    "success_count": 145,
    "failure_count": 5,
    "avg_duration_ms": 32000,
    "total_cost_usd": 18.50,
    "last_run_at": "2025-01-15T10:30:00Z"
  }
]
```

---

### GET /v1/stats

Get aggregate statistics.

**Query Parameters:**
- `agent_id` (optional): Filter by agent
- `since` (optional): ISO date string, filter runs after this time

**Response:** `200 OK`

```json
{
  "total_runs": 1500,
  "completed": 1450,
  "failed": 50,
  "avg_duration_ms": 28000,
  "total_tokens_input": 25000000,
  "total_tokens_output": 5000000,
  "total_cost_usd": 185.00
}
```

---

### GET /v1/tools

Get tool usage statistics.

**Query Parameters:**
- `agent_id` (optional): Filter by agent
- `since` (optional): ISO date string

**Response:** `200 OK`

```json
[
  {
    "tool_name": "WebSearch",
    "call_count": 5000,
    "success_count": 4950,
    "failure_count": 50,
    "avg_duration_ms": 450
  }
]
```

---

### GET /v1/capabilities

Return receiver capabilities for SDK feature negotiation.

**Response:** `200 OK`

```json
{
  "version": "0.1.0",
  "api_version": "v1",
  "features": {
    "streaming_events": true,
    "batch_ingest": false,
    "compression": []
  },
  "limits": {
    "max_events_per_run": 10000,
    "max_payload_bytes": 10000000,
    "retention_days": null
  }
}
```

**Fields:**

- `version`: Receiver implementation version
- `api_version`: API version supported
- `features.streaming_events`: Whether `/v1/runs/{run_id}/events` is supported
- `features.batch_ingest`: Whether batch event ingestion is supported
- `features.compression`: Supported compression algorithms (e.g., `["gzip"]`)
- `limits.max_events_per_run`: Maximum events per run
- `limits.max_payload_bytes`: Maximum request payload size
- `limits.retention_days`: Data retention period (null = unlimited)

---

### GET /health

Health check endpoint.

**Response:** `200 OK`

```json
{
  "status": "healthy",
  "timestamp": "2025-01-15T10:30:00Z"
}
```

---

## Data Types

### RunStatus

```
"running" | "completed" | "failed" | "timeout"
```

### EventType

```
"run_start" | "assistant_message" | "tool_call" | "tool_result" | "error" | "run_end"
```

### TokenUsage

```json
{
  "input": 15000,
  "output": 3200,
  "cache_read": 0,
  "cache_write": 0
}
```

### ErrorInfo

```json
{
  "type": "TimeoutError",
  "message": "Agent exceeded max turns",
  "stack": "optional stack trace"
}
```

---

## Implementation Notes

1. **Idempotency**: Use `run_id` and `event_id` as primary keys. Duplicate submissions should update, not create duplicates.

2. **Async Processing**: Return `202 Accepted` immediately. Process data asynchronously if needed.

3. **Validation**: The SDK sends well-formed data. Light validation is sufficient.

4. **Storage**: The reference implementation uses SQLite. For production, consider PostgreSQL, ClickHouse, or a time-series database.

5. **Retention**: Implement data retention policies as needed. Agent traces can be large.

---

## Example: Minimal Receiver

A minimal receiver only needs to implement `POST /v1/runs`:

```python
from fastapi import FastAPI
import json

app = FastAPI()
runs = []  # In-memory storage

@app.post("/v1/runs", status_code=202)
async def ingest_run(run: dict):
    runs.append(run)
    print(f"Received run: {run['run_id']} - {run['status']}")
    return {"status": "accepted"}
```

That's it. You can build from there.