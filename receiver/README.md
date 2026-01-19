# AgentMetrics Receiver

A minimal, self-hostable receiver for AgentMetrics data. Uses SQLite for storage and FastAPI for the API.

## Quick Start

```bash
pip install -r requirements.txt
python receiver.py
```

The server runs on `http://localhost:8080`.

## Configure SDK to Use Receiver

```python
from agentmetrics import configure

configure(
    endpoint_url="http://localhost:8080",
    agent_id="my-agent",
)
```

## API Endpoints

### Ingest (SDK → Receiver)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/runs` | Receive completed run |
| POST | `/v1/runs/{run_id}/events` | Receive streaming event |

### Query (Dashboard → Receiver)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/runs` | List runs (supports `?agent_id=`, `?status=`, `?limit=`, `?offset=`) |
| GET | `/v1/runs/{run_id}` | Get single run |
| GET | `/v1/runs/{run_id}/events` | Get events for a run |
| GET | `/v1/agents` | List all agents with aggregated stats |
| GET | `/v1/stats` | Aggregate statistics (supports `?agent_id=`, `?since=`) |
| GET | `/v1/tools` | Tool usage statistics |
| GET | `/health` | Health check |

## Example Queries

```bash
# List recent runs
curl http://localhost:8080/v1/runs

# Filter by agent
curl http://localhost:8080/v1/runs?agent_id=my-agent&status=completed

# Get stats
curl http://localhost:8080/v1/stats

# Get tool usage
curl http://localhost:8080/v1/tools
```

## Data Storage

Data is stored in `agentmetrics.db` (SQLite) in the current directory.

### Schema

**runs** table:
- `run_id`, `agent_id`, `session_id`, `status`
- `started_at`, `finished_at`, `duration_ms`
- `tokens_input`, `tokens_output`, `estimated_cost_usd`
- `model`, `error_type`, `error_message`
- `data` (full JSON)

**events** table:
- `event_id`, `run_id`, `type`, `timestamp`
- `tool_name`, `tool_duration_ms`, `tool_success`
- `data` (full JSON)

## Production Deployment

For production, consider:

1. **Use a proper database** (PostgreSQL, MySQL)
2. **Add authentication** (API key validation in headers)
3. **Run with gunicorn**: `gunicorn -w 4 -k uvicorn.workers.UvicornWorker receiver:app`
4. **Add rate limiting**
5. **Set up backups** for the database

## Environment Variables

None required for basic usage. The receiver accepts all requests by default.

To add API key validation, modify the endpoints to check `Authorization` header.
