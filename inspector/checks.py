"""
Stateless check functions. Each returns a list of Anomaly for whatever is wrong right now.
The Inspector handles dedup and decides whether to alert.
"""
from dataclasses import dataclass, field
from k8s.operations import K8sOperations


@dataclass
class Anomaly:
    kind: str          # Pod / Deployment / Node / Event-object-kind
    namespace: str
    name: str
    check_type: str    # high_restarts / not_ready / warning_event_<reason> / node_not_ready
    summary: str
    details: dict = field(default_factory=dict)


def check_pod_restarts(ops: K8sOperations, threshold: int = 3) -> list[Anomaly]:
    pods = ops.get_pods()
    anomalies = []
    for pod in pods:
        if "error" in pod:
            continue
        restarts = pod.get("restarts", 0)
        if restarts >= threshold:
            anomalies.append(Anomaly(
                kind="Pod",
                namespace=pod.get("namespace", "default"),
                name=pod.get("name", ""),
                check_type="high_restarts",
                summary=(
                    f"Pod {pod['namespace']}/{pod['name']} "
                    f"重启次数达到 {restarts} 次，当前状态 {pod.get('status', '?')}"
                ),
                details=pod,
            ))
    return anomalies


def check_deployment_ready(ops: K8sOperations) -> list[Anomaly]:
    deployments = ops.get_deployments()
    anomalies = []
    for dep in deployments:
        if "error" in dep:
            continue
        desired = dep.get("desired") or 0
        ready = dep.get("ready") or 0
        if desired > 0 and ready < desired:
            anomalies.append(Anomaly(
                kind="Deployment",
                namespace=dep.get("namespace", "default"),
                name=dep.get("name", ""),
                check_type="not_ready",
                summary=(
                    f"Deployment {dep['namespace']}/{dep['name']} "
                    f"副本不足（{ready}/{desired} ready）"
                ),
                details=dep,
            ))
    return anomalies


def check_warning_events(ops: K8sOperations) -> list[Anomaly]:
    events = ops.get_events()
    anomalies = []
    for ev in events:
        if "error" in ev:
            continue
        if ev.get("type") != "Warning":
            continue
        obj = ev.get("object", "unknown")        # e.g. "Pod/nginx-abc"
        reason = ev.get("reason", "unknown")
        parts = obj.split("/", 1)
        kind = parts[0] if len(parts) == 2 else "Resource"
        name = parts[1] if len(parts) == 2 else obj
        anomalies.append(Anomaly(
            kind=kind,
            namespace="default",
            name=name,
            check_type=f"warning_{reason}",
            summary=f"Warning 事件 [{reason}] on {obj}: {ev.get('message', '')}",
            details=ev,
        ))
    return anomalies


def check_node_ready(ops: K8sOperations) -> list[Anomaly]:
    nodes = ops.get_nodes()
    anomalies = []
    for node in nodes:
        if "error" in node:
            continue
        if node.get("status") != "Ready":
            anomalies.append(Anomaly(
                kind="Node",
                namespace="",
                name=node.get("name", ""),
                check_type="node_not_ready",
                summary=f"Node {node['name']} 状态异常（{node.get('status', 'Unknown')}）",
                details=node,
            ))
    return anomalies


ALL_CHECKS = [
    check_pod_restarts,
    check_deployment_ready,
    check_warning_events,
    check_node_ready,
]
