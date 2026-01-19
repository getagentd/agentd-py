# Contributing to AgentMetrics

Thanks for your interest in contributing to AgentMetrics!

## Development Setup

```bash
# Clone the repo
git clone https://github.com/getagentd/agentd-py.git
cd agentwatch-py

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # or `.venv\Scripts\activate` on Windows

# Install in development mode
pip install -e ".[dev]"

# Install the Claude Agent SDK (required for examples)
pip install claude-agent-sdk
```

## Running Tests

```bash
pytest tests/ -v
```

## Code Style

- Use type hints
- Follow PEP 8
- Keep functions focused and small

## Making Changes

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes
4. Run tests (`pytest tests/ -v`)
5. Commit with a clear message
6. Push and open a PR

## What to Contribute

- Bug fixes
- Documentation improvements
- New receiver implementations
- Performance optimizations
- Test coverage

## Questions?

Open an issue or reach out on GitHub Discussions.
