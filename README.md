# AgentD

[![PyPI](https://img.shields.io/pypi/v/agentd-sdk)](https://pypi.org/project/agentd-sdk/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

![https://getagentd.com](./resources/logo.png)


**Observability for AI Agents. Open spec. Self-host or use our platform.**

Drop-in replacement for `claude_agent_sdk.query()` that adds metrics, tracing, and cost tracking.
```python
# Before
from claude_agent_sdk import query

# After (that's it)
from agentd import query
```

---

## Why?

You built an agent. It works locally. Now what?

- **Where do I see what it did?** → AgentD logs every tool call, duration, and token usage
- **How much is this costing me?** → Automatic cost tracking per run
- **Why did it fail?** → Full traces with inputs and outputs

---

## Quick Start

### Install
```bash
pip install agentd-sdk
```

> Requires [Claude Agent SDK](https://github.com/anthropics/claude-code-sdk-python)

### Use
```python
import asyncio
from agentd import query
from claude_agent_sdk import ClaudeAgentOptions

async def main():
    options = ClaudeAgentOptions(
        allowed_tools=["WebSearch", "Read", "Write"],
        permission_mode="acceptEdits",
    )
    
    async for message in query(
        prompt="Research the latest AI agent frameworks",
        options=options,
        agent_id="my-research-agent",  # Optional: group runs
    ):
        print(message)

asyncio.run(main())
```

That's it. You'll see a summary printed after each run:
```
============================================================
📊 AGENT RUN SUMMARY
============================================================
Run ID:     550e8400-e29b-41d4-a716-446655440000
Agent:      my-research-agent
Status:     completed
Duration:   12,340ms, API: 11,200ms, Overhead: 1,140ms
TTFT:       890ms
Turns:      5
Model:      claude-sonnet-4-5-20250929
Tokens:     15,230 in / 3,200 out (cache: 2,100 read)
Cost:       $0.0936 (SDK)
Trace:      a1b2c3d4e5f6a7b8...

📦 Tool Usage:
  • WebSearch: 3x (1200ms) [✓]
  • Read: 2x (50ms) [✓]
  • Write: 1x (30ms) [✓]
============================================================
```

---

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `AGENTD_URL` | HTTP endpoint to send metrics | None (console mode) |
| `AGENTD_API_KEY` | API key for authentication | None |
| `AGENTD_AGENT_ID` | Default agent ID | None |
| `AGENTD_DISABLED` | Set to "true" to disable | false |
| `AGENTD_QUIET` | Set to "true" to suppress console output | false |
| `AGENTD_STREAMING` | Real-time event streaming | false |

### Programmatic Configuration
```python
from agentd import configure

configure(
    endpoint_url="https://your-receiver.com",
    api_key="your-api-key",
    agent_id="default-agent-id",
    include_trace=True,
    include_prompt=False,
)
```

---

## Output Modes

### Console (Default)

No config needed. Prints summary to stdout. Great for local development.
```bash
# Suppress console output
export AGENTD_QUIET=true
```

### HTTP

Set `AGENTD_URL` to send data to a receiver:
```bash
export AGENTD_URL=https://your-receiver.com/v1/runs
export AGENTD_API_KEY=your-key
```

### Disabled
```bash
export AGENTD_DISABLED=true
```

---

## Alternative Usage Patterns

### Wrapper Function

Keep using `claude_agent_sdk.query()` directly:
```python
from claude_agent_sdk import query
from agentd import tracked_query

async for message in tracked_query(
    query(prompt="...", options=options),
    agent_id="my-agent"
):
    print(message)
```

### Context Manager

For fine-grained control:
```python
from claude_agent_sdk import query
from agentd import track_run

async with track_run(agent_id="my-agent") as tracker:
    async for message in query(prompt="...", options=options):
        tracker.process_message(message)
        # Custom processing here
```

---

## Self-Hosting

We provide a [reference receiver implementation](./receiver). Run it, modify it, or use it to learn the spec.

### Quick Start
```bash
cd receiver
pip install -r requirements.txt
python receiver.py
```

The receiver runs at `http://localhost:8080`. Point your SDK at it:
```bash
export AGENTD_URL=http://localhost:8080
```

### What You Get

- SQLite storage (swap for Postgres, ClickHouse, etc.)
- REST API for querying data
- Ready for Grafana dashboards

### API Spec

See [spec/API.md](spec/API.md) for the full API contract. Build your own receiver if you want.

---

## Data Model

### AgentRun
```json
{
  "run_id": "uuid",
  "agent_id": "my-agent",
  "status": "completed",
  "duration_ms": 12340,
  "api_duration_ms": 11200,
  "first_token_ms": 890,
  "num_turns": 5,
  "tokens": {"input": 15230, "output": 3200, "cache_read": 2100, "cache_write": 0},
  "cost_usd": 0.0936,
  "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
  "span_id": "a1b2c3d4e5f6a7b8",
  "tool_calls": [
    {"tool": "WebSearch", "count": 3, "total_duration_ms": 1200}
  ],
  "events": [/* full trace */]
}
```

### RunEvent
```json
{
  "event_id": "uuid",
  "type": "tool_call",
  "timestamp": "2025-01-15T10:30:00Z",
  "sequence_number": 5,
  "tool_name": "WebSearch",
  "tool_id": "toolu_123",
  "tool_input": {"query": "AI agents"},
  "tool_duration_ms": 400,
  "tool_success": true
}
```

---

## Philosophy

1. **Open spec** — The API contract is public. Build your own receiver, use ours, or switch later.
2. **No lock-in** — Remove AgentD and your agent still works. It's just a wrapper.
3. **Start simple** — Console output by default. Add infrastructure as you need it.

---

## License

MIT

---

## Contributing

Issues and PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).