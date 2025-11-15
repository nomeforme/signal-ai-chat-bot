"""
Clean agent abstraction with tool support.

This module provides a clean agent definition system that:
- Separates agent configuration from execution
- Supports Anthropic's native tool calling API
- Allows incremental addition of tools
- Maintains full control over prompts and behavior
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, Literal
import httpx


# Tool system using Anthropic's native tool calling
@dataclass
class Tool:
    """Definition for a tool that agents can use."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], Awaitable[str]]

    def to_anthropic_tool(self) -> dict[str, Any]:
        """Convert to Anthropic API tool format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema
        }


# Built-in tools
async def fetch_handler(args: dict[str, Any]) -> str:
    """Fetch content from a URL."""
    url = args.get("url")
    if not url:
        return "Error: No URL provided"

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()

            # Limit response size to avoid overwhelming context
            content = response.text[:50000]  # ~50KB limit

            return f"Successfully fetched content from {url}:\n\n{content}"
    except httpx.HTTPError as e:
        return f"Error fetching {url}: {str(e)}"
    except Exception as e:
        return f"Unexpected error fetching {url}: {str(e)}"


# Tool registry
AVAILABLE_TOOLS = {
    "fetch": Tool(
        name="fetch",
        description="Fetch content from a URL. Use this to retrieve web pages, APIs, or any HTTP-accessible content.",
        input_schema={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch content from (must be a valid HTTP/HTTPS URL)"
                }
            },
            "required": ["url"]
        },
        handler=fetch_handler
    )
}


@dataclass
class AgentDefinition:
    """
    Clean agent definition with model, prompt, and tool configuration.

    This separates agent configuration from execution, making it easy to:
    - Define multiple agents with different capabilities
    - Share configurations across instances
    - Add/remove tools per agent
    - Maintain clean, readable agent specifications
    """

    name: str
    model: str  # Model identifier (e.g., "claude-sonnet-4-5-20250929")
    system_prompt: str
    tools: list[str] = field(default_factory=list)  # Tool names from AVAILABLE_TOOLS
    description: str = ""  # Human-readable description of agent's purpose

    def get_tools(self) -> list[Tool]:
        """Get Tool instances for this agent's enabled tools."""
        return [AVAILABLE_TOOLS[tool_name] for tool_name in self.tools if tool_name in AVAILABLE_TOOLS]

    def get_anthropic_tools(self) -> list[dict[str, Any]]:
        """Get tools in Anthropic API format."""
        return [tool.to_anthropic_tool() for tool in self.get_tools()]

    async def execute_tool(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        """Execute a tool by name with given input."""
        if tool_name not in self.tools:
            return f"Error: Tool '{tool_name}' not enabled for this agent"

        if tool_name not in AVAILABLE_TOOLS:
            return f"Error: Tool '{tool_name}' not found in registry"

        tool = AVAILABLE_TOOLS[tool_name]
        return await tool.handler(tool_input)


def create_agent_from_config(bot_config: dict[str, Any], system_prompt: str) -> AgentDefinition:
    """
    Create an AgentDefinition from bot configuration.

    Args:
        bot_config: Bot config dict with name, model, etc.
        system_prompt: The system prompt to use for this agent

    Returns:
        AgentDefinition instance
    """
    # Extract clean model name (remove the number prefix)
    model_key = bot_config.get("model", "")
    if " " in model_key:
        model_name = model_key.split(" ", 1)[1]
    else:
        model_name = model_key

    # Get enabled tools from config (default to no tools)
    tools = bot_config.get("tools", [])

    return AgentDefinition(
        name=bot_config.get("name", "unnamed"),
        model=model_name,
        system_prompt=system_prompt,
        tools=tools,
        description=bot_config.get("description", "")
    )