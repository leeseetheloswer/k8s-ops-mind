from __future__ import annotations
from typing import Any
import yaml
from kubernetes import utils
from kubernetes.client.rest import ApiException
from k8s.client import K8sClient
from utils.logger import get_logger

logger = get_logger(__name__)


# ------------------------------------------------------------------ #
# Object → dict helpers（只保留 LLM 有用的字段）
# ------------------------------------------------------------------ #

def _clean(d: Any) -> Any:
    """Recursively remove None values from a dict/list."""
    if isinstance(d, dict):
        return {k: _clean(v) for k, v in d.items() if v is not None}
    if isinstance(d, list):
        return [_clean(i) for i in d if i is not None]
    return d


def _pod_to_dict(pod) -> dict:
    statuses = pod.status.container_statuses or []
    ready_count = sum(1 for s in statuses if s.ready)
    total = len(pod.spec.containers)
    restarts = sum(s.restart_count for s in statuses)
    return {
        "name": pod.metadata.name,
        "namespace": pod.metadata.namespace,
        "status": pod.status.phase,
        "ready": f"{ready_count}/{total}",
        "restarts": restarts,
        "node": pod.spec.node_name,
        "created": str(pod.metadata.creation_timestamp),
    }


def _deployment_to_dict(dep) -> dict:
    return {
        "name": dep.metadata.name,
        "namespace": dep.metadata.namespace,
        "desired": dep.spec.replicas,
        "ready": dep.status.ready_replicas or 0,
        "available": dep.status.available_replicas or 0,
        "created": str(dep.metadata.creation_timestamp),
    }


def _service_to_dict(svc) -> dict:
    ports = [f"{p.port}:{p.target_port}/{p.protocol}" for p in (svc.spec.ports or [])]
    return {
        "name": svc.metadata.name,
        "namespace": svc.metadata.namespace,
        "type": svc.spec.type,
        "cluster_ip": svc.spec.cluster_ip,
        "ports": ports,
        "created": str(svc.metadata.creation_timestamp),
    }


def _node_to_dict(node) -> dict:
    conditions = {c.type: c.status for c in (node.status.conditions or [])}
    roles = [
        k.split("/")[-1]
        for k in (node.metadata.labels or {})
        if "node-role.kubernetes.io/" in k
    ]
    return {
        "name": node.metadata.name,
        "status": "Ready" if conditions.get("Ready") == "True" else "NotReady",
        "roles": ",".join(roles) or "worker",
        "kubelet_version": (node.status.node_info.kubelet_version if node.status.node_info else ""),
        "created": str(node.metadata.creation_timestamp),
    }


def _event_to_dict(event) -> dict:
    return {
        "type": event.type,
        "reason": event.reason,
        "message": event.message,
        "object": f"{event.involved_object.kind}/{event.involved_object.name}",
        "count": event.count,
        "last_time": str(event.last_timestamp or event.event_time),
    }


# ------------------------------------------------------------------ #
# Operations
# ------------------------------------------------------------------ #

class K8sOperations:
    def __init__(self, client: K8sClient):
        self.client = client

    # --- Read --------------------------------------------------------

    def get_pods(self, namespace: str | None = None) -> list[dict[str, Any]]:
        ns = namespace or self.client.namespace
        try:
            ret = self.client.core.list_namespaced_pod(namespace=ns)
            return [_pod_to_dict(p) for p in ret.items]
        except ApiException as e:
            return [{"error": str(e)}]

    def get_deployments(self, namespace: str | None = None) -> list[dict[str, Any]]:
        ns = namespace or self.client.namespace
        try:
            ret = self.client.apps.list_namespaced_deployment(namespace=ns)
            return [_deployment_to_dict(d) for d in ret.items]
        except ApiException as e:
            return [{"error": str(e)}]

    def get_services(self, namespace: str | None = None) -> list[dict[str, Any]]:
        ns = namespace or self.client.namespace
        try:
            ret = self.client.core.list_namespaced_service(namespace=ns)
            return [_service_to_dict(s) for s in ret.items]
        except ApiException as e:
            return [{"error": str(e)}]

    def get_nodes(self) -> list[dict[str, Any]]:
        try:
            ret = self.client.core.list_node()
            return [_node_to_dict(n) for n in ret.items]
        except ApiException as e:
            return [{"error": str(e)}]

    def get_events(self, namespace: str | None = None) -> list[dict[str, Any]]:
        ns = namespace or self.client.namespace
        try:
            ret = self.client.core.list_namespaced_event(namespace=ns)
            events = sorted(
                ret.items,
                key=lambda e: e.last_timestamp or e.event_time or "",
                reverse=True,
            )
            return [_event_to_dict(e) for e in events[:20]]
        except ApiException as e:
            return [{"error": str(e)}]

    def describe_resource(self, kind: str, name: str, namespace: str | None = None) -> dict[str, Any]:
        ns = namespace or self.client.namespace
        try:
            k = kind.lower()
            if k == "pod":
                obj = self.client.core.read_namespaced_pod(name=name, namespace=ns)
            elif k == "deployment":
                obj = self.client.apps.read_namespaced_deployment(name=name, namespace=ns)
            elif k == "service":
                obj = self.client.core.read_namespaced_service(name=name, namespace=ns)
            elif k == "node":
                obj = self.client.core.read_node(name=name)
            else:
                return {"error": f"不支持的资源类型: {kind}，支持 Pod/Deployment/Service/Node"}
            return _clean(obj.to_dict())
        except ApiException as e:
            return {"error": str(e)}

    def get_logs(self, pod_name: str, namespace: str | None = None, tail_lines: int = 50) -> str:
        ns = namespace or self.client.namespace
        try:
            return self.client.core.read_namespaced_pod_log(
                name=pod_name,
                namespace=ns,
                tail_lines=tail_lines,
            )
        except ApiException as e:
            return f"Error: {e}"

    # --- Write -------------------------------------------------------

    def scale_deployment(self, name: str, replicas: int, namespace: str | None = None) -> dict[str, Any]:
        ns = namespace or self.client.namespace
        try:
            self.client.apps.patch_namespaced_deployment_scale(
                name=name,
                namespace=ns,
                body={"spec": {"replicas": replicas}},
            )
            return {"success": True, "name": name, "namespace": ns, "replicas": replicas}
        except ApiException as e:
            return {"success": False, "error": str(e)}

    def apply_manifest(self, yaml_content: str) -> dict[str, Any]:
        """Apply a YAML manifest (create only; does not patch existing resources)."""
        try:
            docs = [d for d in yaml.safe_load_all(yaml_content) if d]
            created = []
            for doc in docs:
                utils.create_from_dict(
                    self.client._api_client,
                    doc,
                    namespace=self.client.namespace,
                )
                created.append({
                    "kind": doc.get("kind"),
                    "name": doc.get("metadata", {}).get("name"),
                })
            return {"success": True, "created": created}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_resource(self, kind: str, name: str, namespace: str | None = None) -> dict[str, Any]:
        ns = namespace or self.client.namespace
        try:
            k = kind.lower()
            if k == "pod":
                self.client.core.delete_namespaced_pod(name=name, namespace=ns)
            elif k == "deployment":
                self.client.apps.delete_namespaced_deployment(name=name, namespace=ns)
            elif k == "service":
                self.client.core.delete_namespaced_service(name=name, namespace=ns)
            else:
                return {"success": False, "error": f"不支持的资源类型: {kind}"}
            return {"success": True, "kind": kind, "name": name, "namespace": ns}
        except ApiException as e:
            return {"success": False, "error": str(e)}
