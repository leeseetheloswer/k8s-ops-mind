"""
Background inspector: runs checks periodically, deduplicates, asks LLM to diagnose,
broadcasts alerts to all connected SSE clients, and fires any registered notifiers.
"""
import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any

from inspector.checks import ALL_CHECKS, Anomaly, check_pod_restarts
from inspector.notifier import AlertNotifier, LogNotifier
from k8s.operations import K8sOperations
from utils.json_util import dumps as json_dumps
from utils.log_filter import filter_logs_for_llm
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
        self._stopped = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="inspector-llm")

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
        """Build the LLM diagnosis prompt. May call K8s API for logs — runs in thread pool."""
        ns = anomaly.namespace or "cluster"
        resource_id = f"{anomaly.kind} {ns}/{anomaly.name}"

        log_section = ""
        if anomaly.kind == "Pod" and anomaly.namespace:
            # For crash/restart anomalies, the previous container's logs capture the
            # actual failure; current logs may be empty or show a fresh (healthy) start.
            use_previous = anomaly.check_type == "high_restarts"
            raw = self._ops.get_logs(
                anomaly.name, anomaly.namespace,
                tail_lines=200, previous=use_previous,
            )
            # Fall back to current logs if previous are unavailable
            if use_previous and raw.startswith("Error:"):
                raw = self._ops.get_logs(anomaly.name, anomaly.namespace, tail_lines=200)
            label = "上一次崩溃日志" if use_previous else "近期日志"
            filtered = filter_logs_for_llm(raw, context_lines=3, max_duplicates=3)
            log_section = f"\n**{label}（预处理后）**：\n```\n{filtered}\n```\n"

        return (
            f"Kubernetes 集群巡检发现异常，请分析并给出排查建议。\n\n"
            f"**受影响资源**：{resource_id}\n"
            f"**异常摘要**：{anomaly.summary}\n"
            f"**资源详情**：\n```json\n{json_dumps(anomaly.details, indent=2)}\n```"
            f"{log_section}\n"
            f"要求：\n"
            f"1. 回答开头必须写明受影响的资源全名（{resource_id}）\n"
            f"2. 给出诊断结论（是否真的有问题，原因是什么）\n"
            f"3. 给出具体操作建议（kubectl 命令优先）\n"
            f"4. 不超过 200 字"
        )

    def _diagnose_sync(self, anomaly: Anomaly) -> str:
        """Blocking: fetch logs, build prompt, call LLM. Runs entirely in thread pool."""
        prompt = self._build_prompt(anomaly)
        self._agent.reset()
        return self._agent.chat(prompt)

    def stop(self) -> None:
        """Signal the inspector to stop and cancel any pending LLM calls."""
        self._stopped = True
        self._executor.shutdown(wait=False, cancel_futures=True)

    async def _diagnose(self, anomaly: Anomaly) -> str:
        if self._stopped:
            return ""
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(self._executor, self._diagnose_sync, anomaly)
        except Exception as e:
            logger.error(f"Diagnosis failed: {e}")
            return f"（诊断失败: {e}）"

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
