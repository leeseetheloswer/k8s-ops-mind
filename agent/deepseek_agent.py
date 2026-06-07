"""
DeepSeek agent — uses the OpenAI-compatible API with tool calling.
Tool dispatch logic mirrors K8sAgent; only the API format differs.
"""
import json
from typing import Any
from openai import OpenAI
from agent.tools import TOOLS
from agent.prompts import SYSTEM_PROMPT
from k8s.operations import K8sOperations
from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)

# Convert Anthropic-style tool schema to OpenAI function-calling format
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
        )
        self.history: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

    def _dispatch_tool(self, tool_name: str, tool_input: dict[str, Any]) -> Any:
        method = getattr(self.ops, tool_name, None)
        if method is None:
            return {"error": f"unknown tool: {tool_name}"}
        return method(**tool_input)

    def chat(self, user_message: str) -> str:
        self.history.append({"role": "user", "content": user_message})

        while True:
            response = self.client.chat.completions.create(
                model=settings.deepseek_model,
                messages=self.history,
                tools=_OPENAI_TOOLS,
                max_tokens=settings.agent_max_tokens,
            )

            choice = response.choices[0]
            # Append the raw assistant message (may contain tool_calls)
            self.history.append(choice.message)

            if choice.finish_reason == "stop":
                return choice.message.content or ""

            if choice.finish_reason == "tool_calls":
                for tool_call in choice.message.tool_calls:
                    name = tool_call.function.name
                    args = json.loads(tool_call.function.arguments)
                    logger.info(f"Calling tool: {name}({args})")
                    result = self._dispatch_tool(name, args)
                    self.history.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    })
                continue

            logger.warning(f"Unexpected finish_reason: {choice.finish_reason}")
            break

        return "(agent loop ended unexpectedly)"

    def reset(self) -> None:
        self.history = [{"role": "system", "content": SYSTEM_PROMPT}]
