"""
Background inspector: runs checks periodically, deduplicates, asks LLM to diagnose,
broadcasts alerts to all connected SSE clients, and fires any registered notifiers.
"""
import asyncio
import uuid
from datetime import datetime, timedelta
from typing import Any

from inspector.checks import ALL_CHECKS, Anomaly, check_pod_restarts
from inspector.notifier import AlertNotifier, LogNotifier
from k8s.operations import K8sOperations
from utils.json_util import dumps as json_dumps
from utils.logger import get_logger

logger = get_logger(__name__)


class Inspector:
    def __init__(
        self,
        ops: K8sOperations,
        agent,
        interval: int = 60,
        cooldown_minutes: int = 30,
        restart_threshold: int = 3,
        notifiers: list[AlertNotifier] | None = None,
    ):
        self._ops = ops
        self._agent = agent
        self._interval = interval
        self._cooldown = timedelta(minutes=cooldown_minutes)
        self._restart_threshold = restart_threshold
        self._notifiers: list[AlertNotifier] = notifiers or [LogNotifier()]
        self._seen: dict[str, datetime] = {}
        self._listeners: list[asyncio.Queue] = []

    # ── SSE subscription ────────────────────────────────────────────── #

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._listeners.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._listeners.remove(q)
        except ValueError:
            pass

    # ── Deduplication ───────────────────────────────────────────────── #

    def _dedup_key(self, anomaly: Anomaly) -> str:
        return f"{anomaly.kind}:{anomaly.namespace}:{anomaly.name}:{anomaly.check_type}"

    def _is_suppressed(self, anomaly: Anomaly) -> bool:
        last = self._seen.get(self._dedup_key(anomaly))
        return last is not None and datetime.now() - last < self._cooldown

    def _mark_seen(self, anomaly: Anomaly) -> None:
        self._seen[self._dedup_key(anomaly)] = datetime.now()

    # ── LLM diagnosis ───────────────────────────────────────────────── #

    def _build_prompt(self, anomaly: Anomaly) -> str:
        return (
            "以下是 Kubernetes 集群巡检发现的一个异常，请分析原因并给出排查建议：\n\n"
            f"**资源**：{anomaly.kind} {anomaly.namespace}/{anomaly.name}\n"
            f"**摘要**：{anomaly.summary}\n"
            f"**详情**：\n```json\n{json_dumps(anomaly.details, indent=2)}\n```\n\n"
            "请直接给出诊断结论和具体操作建议，不超过 200 字。"
        )

    async def _diagnose(self, anomaly: Anomaly) -> str:
        prompt = self._build_prompt(anomaly)
        loop = asyncio.get_event_loop()
        try:
            # agent.chat is synchronous — run in thread pool to avoid blocking event loop
            self._agent.reset()
            return await loop.run_in_executor(None, self._agent.chat, prompt)
        except Exception as e:
            logger.error(f"Diagnosis LLM call failed: {e}")
            return f"（LLM 诊断失败: {e}）"

    # ── Broadcast & notify ──────────────────────────────────────────── #

    async def _broadcast(self, alert: dict[str, Any]) -> None:
        for q in list(self._listeners):
            await q.put(alert)

    async def _notify(self, alert: dict[str, Any]) -> None:
        for notifier in self._notifiers:
            try:
                await notifier.send(alert)
            except Exception as e:
                logger.error(f"Notifier {notifier} failed: {e}")

    # ── Main loop ───────────────────────────────────────────────────── #

    async def run_once(self) -> None:
        logger.info("Inspector: running checks")
        anomalies: list[Anomaly] = []
        try:
            for check_fn in ALL_CHECKS:
                # check_pod_restarts needs threshold arg
                if check_fn is check_pod_restarts:
                    anomalies += check_fn(self._ops, self._restart_threshold)
                else:
                    anomalies += check_fn(self._ops)
        except Exception as e:
            logger.error(f"Inspector checks error: {e}")
            return

        for anomaly in anomalies:
            if self._is_suppressed(anomaly):
                continue
            self._mark_seen(anomaly)

            diagnosis = await self._diagnose(anomaly)
            alert: dict[str, Any] = {
                "id": str(uuid.uuid4()),
                "timestamp": datetime.now().isoformat(),
                "kind": anomaly.kind,
                "namespace": anomaly.namespace,
                "name": anomaly.name,
                "check_type": anomaly.check_type,
                "summary": anomaly.summary,
                "diagnosis": diagnosis,
            }
            logger.warning(f"[Alert] {anomaly.summary}")
            await self._broadcast(alert)
            await self._notify(alert)

    async def start(self) -> None:
        logger.info(
            f"Inspector started — interval={self._interval}s  "
            f"cooldown={self._cooldown}  threshold={self._restart_threshold}"
        )
        while True:
            try:
                await self.run_once()
            except Exception as e:
                logger.error(f"Inspector loop error: {e}")
            await asyncio.sleep(self._interval)
