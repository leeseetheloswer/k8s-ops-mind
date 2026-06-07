"""
Webhook notifier interface and stub implementations.

To add a new channel (Feishu, WeChat, PagerDuty, etc.):
  1. Implement the AlertNotifier Protocol
  2. Instantiate and pass to Inspector(notifiers=[...])
"""
from typing import Protocol, runtime_checkable
from utils.logger import get_logger

logger = get_logger(__name__)


@runtime_checkable
class AlertNotifier(Protocol):
    async def send(self, alert: dict) -> None: ...


class LogNotifier:
    """Default notifier — logs the alert summary."""
    async def send(self, alert: dict) -> None:
        logger.warning(f"[Inspector Alert] {alert.get('summary')}")


# ── Future implementations (not active) ────────────────────────────── #
#
# class FeiShuNotifier:
#     def __init__(self, webhook_url: str):
#         self._url = webhook_url
#
#     async def send(self, alert: dict) -> None:
#         import httpx
#         payload = {"msg_type": "text", "content": {"text": alert["summary"]}}
#         async with httpx.AsyncClient() as client:
#             await client.post(self._url, json=payload)
#
#
# class WeChatWorkNotifier:
#     def __init__(self, webhook_url: str):
#         self._url = webhook_url
#
#     async def send(self, alert: dict) -> None:
#         import httpx
#         payload = {"msgtype": "text", "text": {"content": alert["summary"]}}
#         async with httpx.AsyncClient() as client:
#             await client.post(self._url, json=payload)
