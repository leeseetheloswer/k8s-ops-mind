"""
DeepSeek agent — uses the OpenAI-compatible API with tool calling.
"""
import json
from typing import Any
from openai import OpenAI
from agent.tools import TOOLS
from agent.prompts import SYSTEM_PROMPT
from agent.confirmation import DANGEROUS_TOOLS, ConfirmationRequired
from k8s.operations import K8sOperations
from config.settings import settings
from utils.logger import get_logger
from utils.json_util import dumps as json_dumps

logger = get_logger(__name__)

_OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["input_schema"],
        },
    }
    for t in TOOLS
]


class DeepSeekAgent:
    def __init__(self, ops: K8sOperations):
        self.ops = ops
        self.client = OpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            timeout=30,
        )
        self.history: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

    def _dispatch_tool(self, tool_name: str, tool_input: dict[str, Any]) -> Any:
        method = getattr(self.ops, tool_name, None)
        if method is None:
            return {"error": f"unknown tool: {tool_name}"}
        return method(**tool_input)

    def _run_loop(self) -> str:
        """Core agentic loop — runs until stop or ConfirmationRequired."""
        while True:
            response = self.client.chat.completions.create(
                model=settings.deepseek_model,
                messages=self.history,
                tools=_OPENAI_TOOLS,
                max_tokens=settings.agent_max_tokens,
            )
            choice = response.choices[0]
            self.history.append(choice.message)

            if choice.finish_reason == "stop":
                return choice.message.content or ""

            if choice.finish_reason == "tool_calls":
                for tool_call in choice.message.tool_calls:
                    name = tool_call.function.name
                    args = json.loads(tool_call.function.arguments)
                    if name in DANGEROUS_TOOLS:
                        desc = DANGEROUS_TOOLS[name](args)
                        assistant_msg = self.history.pop()  # roll back before raising
                        raise ConfirmationRequired(name, args, tool_call.id, desc, assistant_msg)
                    logger.info(f"Calling tool: {name}({args})")
                    result = self._dispatch_tool(name, args)
                    self.history.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json_dumps(result),
                    })
                continue

            logger.warning(f"Unexpected finish_reason: {choice.finish_reason}")
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
            "role": "tool",
            "tool_call_id": tool_id,
            "content": json_dumps(result),
        })
        return self._run_loop()

    def reset(self) -> None:
        self.history = [{"role": "system", "content": SYSTEM_PROMPT}]
