from typing import Any
import anthropic
from agent.tools import TOOLS
from agent.prompts import SYSTEM_PROMPT
from agent.confirmation import DANGEROUS_TOOLS, ConfirmationRequired
from k8s.operations import K8sOperations
from config.settings import settings
from utils.logger import get_logger
from utils.json_util import dumps as json_dumps

logger = get_logger(__name__)


class K8sAgent:
    def __init__(self, ops: K8sOperations):
        self.ops = ops
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=30)
        self._model = settings.anthropic_model
        self.history: list[dict[str, Any]] = []

    def _dispatch_tool(self, tool_name: str, tool_input: dict[str, Any]) -> Any:
        method = getattr(self.ops, tool_name, None)
        if method is None:
            return {"error": f"unknown tool: {tool_name}"}
        return method(**tool_input)

    def _run_tool_calls(self, tool_use_blocks: list) -> list[dict[str, Any]]:
        tool_results = []
        for block in tool_use_blocks:
            if block.name in DANGEROUS_TOOLS:
                desc = DANGEROUS_TOOLS[block.name](block.input)
                assistant_msg = self.history.pop()  # roll back before raising
                raise ConfirmationRequired(block.name, block.input, block.id, desc, assistant_msg)
            logger.info(f"Calling tool: {block.name}({block.input})")
            result = self._dispatch_tool(block.name, block.input)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json_dumps(result),
            })
        return tool_results

    def _run_loop(self) -> str:
        """Core agentic loop — runs until end_turn or ConfirmationRequired."""
        while True:
            response = self.client.messages.create(
                model=self._model,
                max_tokens=settings.agent_max_tokens,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=self.history,
            )
            self.history.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                for block in response.content:
                    if hasattr(block, "text"):
                        return block.text
                return ""

            if response.stop_reason == "tool_use":
                tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
                tool_results = self._run_tool_calls(tool_use_blocks)  # may raise ConfirmationRequired
                self.history.append({"role": "user", "content": tool_results})
                continue

            logger.warning(f"Unexpected stop_reason: {response.stop_reason}")
            break

        return "(agent loop ended unexpectedly)"

    def chat(self, user_message: str) -> str:
        self.history.append({"role": "user", "content": user_message})
        return self._run_loop()

    def execute_confirmed(self, tool_name: str, tool_input: dict, tool_id: str,
                          assistant_msg=None) -> str:
        """Execute a previously confirmed dangerous operation and resume the loop."""
        logger.info(f"Executing confirmed: {tool_name}({tool_input})")
        if assistant_msg is not None:
            self.history.append(assistant_msg)
        result = self._dispatch_tool(tool_name, tool_input)
        self.history.append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": json_dumps(result),
            }],
        })
        return self._run_loop()

    def reset(self) -> None:
        self.history.clear()
