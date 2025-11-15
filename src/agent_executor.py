"""
Agent execution with tool calling support.

Handles the agentic loop:
1. Send message with tools to Claude
2. If Claude uses a tool, execute it
3. Send tool results back to Claude
4. Repeat until Claude responds with text
"""

import anthropic
from typing import Any
from agent import AgentDefinition


async def execute_agent_turn(
    client: anthropic.Anthropic,
    agent: AgentDefinition,
    messages: list[dict[str, Any]],
    max_tool_rounds: int = 5
) -> tuple[str, list[dict[str, Any]]]:
    """
    Execute one turn of agent interaction with tool support.

    Args:
        client: Anthropic client instance
        agent: AgentDefinition with tools
        messages: Conversation history (Claude format)
        max_tool_rounds: Maximum tool use iterations to prevent loops

    Returns:
        Tuple of (final_response_text, updated_messages)
    """
    working_messages = messages.copy()
    tool_rounds = 0

    while tool_rounds < max_tool_rounds:
        # Prepare API call
        api_params = {
            "model": agent.model,
            "max_tokens": 4096,
            "messages": working_messages,
        }

        # Add system prompt if present
        if agent.system_prompt:
            api_params["system"] = agent.system_prompt

        # Add tools if agent has any enabled
        if agent.tools:
            api_params["tools"] = agent.get_anthropic_tools()

        # Call Claude
        response = client.messages.create(**api_params)

        # Check stop reason
        if response.stop_reason == "end_turn":
            # Claude finished - extract text response
            text_content = []
            for block in response.content:
                if block.type == "text":
                    text_content.append(block.text)

            final_text = "\n".join(text_content)

            # Add assistant message to history
            working_messages.append({
                "role": "assistant",
                "content": response.content
            })

            return final_text, working_messages

        elif response.stop_reason == "tool_use":
            # Claude wants to use tools
            tool_results = []

            for block in response.content:
                if block.type == "tool_use":
                    # Execute the tool
                    tool_result = await agent.execute_tool(block.name, block.input)

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": tool_result
                    })

            # Add assistant's tool use to messages
            working_messages.append({
                "role": "assistant",
                "content": response.content
            })

            # Add tool results as user message
            working_messages.append({
                "role": "user",
                "content": tool_results
            })

            tool_rounds += 1
            continue  # Loop back to get Claude's response to tool results

        else:
            # Unexpected stop reason
            print(f"Warning: Unexpected stop_reason: {response.stop_reason}")
            # Try to extract any text content
            text_content = []
            for block in response.content:
                if block.type == "text":
                    text_content.append(block.text)

            final_text = "\n".join(text_content) if text_content else "Sorry, I encountered an error."

            working_messages.append({
                "role": "assistant",
                "content": response.content
            })

            return final_text, working_messages

    # Max tool rounds exceeded
    print(f"Warning: Max tool rounds ({max_tool_rounds}) exceeded")
    return "Sorry, I got stuck in a loop trying to use tools. Please try rephrasing your request.", working_messages
