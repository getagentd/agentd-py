"""
Example: Using agentd with multiple MCP servers

Demonstrates configuring multiple MCP tools (filesystem, fetch, memory)
and tracking their usage with agentd.
"""

import asyncio
import os
from agentd import query
from claude_agent_sdk import ClaudeAgentOptions


async def main():
    # Create workspace directory
    workspace = os.path.expanduser("~/mcp-workspace")
    os.makedirs(workspace, exist_ok=True)

    # Configure multiple MCP servers
    options = ClaudeAgentOptions(
        mcp_servers={
            # Filesystem server - read/write files
            "filesystem": {
                "command": "npx",
                "args": ["-y", "@anthropic/mcp-filesystem", workspace],
            },
            # Fetch server - make HTTP requests
            "fetch": {
                "command": "npx",
                "args": ["-y", "@anthropic/mcp-fetch"],
            },
            # Memory server - persistent key-value storage
            "memory": {
                "command": "npx",
                "args": ["-y", "@anthropic/mcp-memory"],
            },
        },
        permission_mode="acceptEdits",
        max_turns=20,
    )

    print("Running agent with filesystem, fetch, and memory tools...\n")

    async for message in query(
        prompt="""You have access to filesystem, fetch, and memory tools.

Complete these tasks:
1. Fetch the README from https://raw.githubusercontent.com/anthropics/anthropic-cookbook/main/README.md
2. Save a summary of it to ~/mcp-workspace/cookbook-summary.txt
3. Store the key topics in memory under the key "cookbook-topics"
4. List what you stored in memory to confirm

Report your progress as you go.
""",
        options=options,
        agent_id="multi-tool-agent",
        metadata={
            "tools": ["filesystem", "fetch", "memory"],
            "task": "cookbook-analysis",
        },
    ):
        if hasattr(message, "content"):
            for block in getattr(message, "content", []):
                if hasattr(block, "text"):
                    print(block.text)


if __name__ == "__main__":
    asyncio.run(main())
