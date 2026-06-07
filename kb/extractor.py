"""
Extract a structured fault case from conversation history using a single LLM call.

Deliberately does NOT use the K8sAgent class to avoid polluting session history.
Falls back gracefully — if extraction fails, nothing is stored.
"""
import json
import re
from utils.logger import get_logger

logger = get_logger(__name__)

# Keywords that suggest the assistant gave a diagnostic conclusion
_DIAGNOSIS_KEYWORDS = [
    '根因', '原因', '建议', '修复', '处置', '解决方案',
    '结论', '诊断', '排查', '问题出在', '导致', '应该',
]

_EXTRACT_PROMPT = """\
分析以下 Kubernetes 运维对话，判断助手是否给出了明确的故障根因结论。

如果给出了根因结论，以 JSON 格式返回（只输出 JSON，不要其他内容）：
{{
  "has_conclusion": true,
  "symptom": "故障现象，一句话",
  "root_cause": "根因分析结论",
  "solution": "处置方案",
  "resource_kind": "涉及的资源类型（Pod/Deployment/Node），没有则空字符串",
  "resource_name": "资源名称，没有则空字符串",
  "namespace": "命名空间，没有则空字符串"
}}

如果只是普通查询没有根因结论，返回：
{{"has_conclusion": false}}

对话记录：
{history}
"""


# ── History formatting ─────────────────────────────────────────────── #

def _fmt_history(history: list) -> str:
    """Convert agent history (either Claude or DeepSeek format) to plain text."""
    lines = []
    for msg in history:
        role = msg.get('role', '')
        if role == 'system':
            continue
        content = msg.get('content', '')

        if role == 'user':
            if isinstance(content, str):
                lines.append(f"[用户] {content[:600]}")
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get('type') == 'text':
                        lines.append(f"[用户] {item['text'][:600]}")
                    # skip tool_result blocks

        elif role == 'assistant':
            if isinstance(content, str):
                lines.append(f"[助手] {content[:1200]}")
            elif isinstance(content, list):
                for item in content:
                    # Anthropic ContentBlock objects
                    if hasattr(item, 'text'):
                        lines.append(f"[助手] {item.text[:1200]}")
                    elif isinstance(item, dict) and item.get('type') == 'text':
                        lines.append(f"[助手] {item['text'][:1200]}")
                    # skip tool_use blocks

        # skip role=tool (DeepSeek tool results)

    return '\n'.join(lines[-30:])  # cap at last 30 exchanges


def _parse_json(text: str) -> dict | None:
    text = text.strip()
    # Strip markdown code fences if present
    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if m:
        text = m.group(1)
    else:
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            text = m.group(0)
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


# ── Lightweight heuristic gate ─────────────────────────────────────── #

def should_extract(history: list, last_response: str) -> bool:
    """
    Cheap check before spending an LLM call on extraction.
    Returns True only when the response is long and diagnostic-looking.
    """
    if len(history) < 4:
        return False
    if len(last_response) < 80:
        return False
    return any(kw in last_response for kw in _DIAGNOSIS_KEYWORDS)


# ── Direct LLM calls (no agent, no history side-effects) ───────────── #

def _call_anthropic(prompt: str) -> str:
    import anthropic
    from config.settings import settings
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=20)
    resp = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text if resp.content else ""


def _call_openai(prompt: str) -> str:
    from openai import OpenAI
    from config.settings import settings
    client = OpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        timeout=20,
    )
    resp = client.chat.completions.create(
        model=settings.deepseek_model,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content or ""


# ── Public API ─────────────────────────────────────────────────────── #

def extract_case(history: list) -> dict | None:
    """
    Call LLM to extract a fault case from session history.
    Returns a dict with symptom/root_cause/solution/... or None.
    Safe to call from a background thread.
    """
    history_text = _fmt_history(history)
    if not history_text.strip():
        return None

    prompt = _EXTRACT_PROMPT.format(history=history_text)

    try:
        from config.settings import settings
        raw = _call_anthropic(prompt) if settings.llm_provider == 'anthropic' else _call_openai(prompt)
        data = _parse_json(raw)
        if data and data.get('has_conclusion'):
            logger.info(f"Extracted case: {data.get('symptom', '')[:60]}")
            return data
    except Exception as e:
        logger.error(f"Case extraction failed: {e}")

    return None
