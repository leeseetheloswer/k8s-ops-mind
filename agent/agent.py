import json
from typing import Any
import anthropic
from agent.tools import TOOLS
from agent.prompts import SYSTEM_PROMPT
from k8s.operations import K8sOperations
from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)


class K8sAgent:
    def __init__(self, ops: K8sOperations):
        self.ops = ops
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._model = settings.anthropic_model
        self.history: list[dict[str, Any]] = []

    def _dispatch_tool(self, tool_name: str, tool_input: dict[str, Any]) -> Any:
        """Route tool call to the corresponding K8sOperations method."""
        method = getattr(self.ops, tool_name, None)
        if method is None:
            return {"error": f"unknown tool: {tool_name}"}
        return method(**tool_input)

    def _run_tool_calls(self, tool_use_blocks: list) -> list[dict[str, Any]]:
        """Execute all tool calls from a response and return tool-result messages."""
        tool_results = []
        for block in tool_use_blocks:
            logger.info(f"Calling tool: {block.name}({block.input})")
            result = self._dispatch_tool(block.name, block.input)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result, ensure_ascii=False),
            })
        return tool_results

    def chat(self, user_message: str) -> str:
        """Send a message and run the agent loop until a final answer is produced."""
        self.history.append({"role": "user", "content": user_message})

        while True:
            response = self.client.messages.create(
                model=self._model,
                max_tokens=settings.agent_max_tokens,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=self.history,
            )

            # Append assistant turn to history
            self.history.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                # Extract the final text reply
                for block in response.content:
                    if hasattr(block, "text"):
                        return block.text
                return ""

            if response.stop_reason == "tool_use":
                tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
                tool_results = self._run_tool_calls(tool_use_blocks)
                self.history.append({"role": "user", "content": tool_results})
                # Loop back to get the next model response
                continue

            # Unexpected stop reason
            logger.warning(f"Unexpected stop_reason: {response.stop_reason}")
            break

        return "(agent loop ended unexpectedly)"

    def reset(self) -> None:
        """Clear conversation history."""
        self.history.clear()
