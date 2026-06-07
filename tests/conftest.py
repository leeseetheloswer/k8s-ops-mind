import os
import pytest
from unittest.mock import MagicMock

# 必须在 settings 模块被导入前设置，否则 pydantic validation 报错
os.environ.setdefault("LLM_PROVIDER", "anthropic")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-anthropic")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test-deepseek")


# ------------------------------------------------------------------ #
# K8s 对象 mock 工厂
# ------------------------------------------------------------------ #

def make_pod(name="nginx-abc", namespace="default", phase="Running",
             ready=True, restarts=0, node="node-1"):
    pod = MagicMock()
    pod.metadata.name = name
    pod.metadata.namespace = namespace
    pod.metadata.creation_timestamp = "2026-01-01T00:00:00Z"
    pod.status.phase = phase
    pod.spec.node_name = node
    pod.spec.containers = [MagicMock()]
    cs = MagicMock()
    cs.ready = ready
    cs.restart_count = restarts
    pod.status.container_statuses = [cs]
    return pod


def make_deployment(name="nginx", namespace="default", replicas=2, ready=2):
    dep = MagicMock()
    dep.metadata.name = name
    dep.metadata.namespace = namespace
    dep.metadata.creation_timestamp = "2026-01-01T00:00:00Z"
    dep.spec.replicas = replicas
    dep.status.ready_replicas = ready
    dep.status.available_replicas = ready
    return dep


def make_service(name="nginx-svc", namespace="default", svc_type="ClusterIP", port=80):
    svc = MagicMock()
    svc.metadata.name = name
    svc.metadata.namespace = namespace
    svc.metadata.creation_timestamp = "2026-01-01T00:00:00Z"
    svc.spec.type = svc_type
    svc.spec.cluster_ip = "10.96.0.1"
    p = MagicMock()
    p.port = port
    p.target_port = port
    p.protocol = "TCP"
    svc.spec.ports = [p]
    return svc


def make_node(name="node-1", ready=True, version="v1.29.0"):
    node = MagicMock()
    node.metadata.name = name
    node.metadata.creation_timestamp = "2026-01-01T00:00:00Z"
    node.metadata.labels = {"node-role.kubernetes.io/control-plane": ""}
    cond = MagicMock()
    cond.type = "Ready"
    cond.status = "True" if ready else "False"
    node.status.conditions = [cond]
    node.status.node_info.kubelet_version = version
    return node


def make_event(event_type="Warning", reason="BackOff",
               message="Container restarting", count=3):
    ev = MagicMock()
    ev.type = event_type
    ev.reason = reason
    ev.message = message
    ev.count = count
    ev.involved_object.kind = "Pod"
    ev.involved_object.name = "nginx-abc"
    ev.last_timestamp = "2026-01-01T00:01:00Z"
    ev.event_time = None
    return ev


# ------------------------------------------------------------------ #
# 共享 fixtures
# ------------------------------------------------------------------ #

@pytest.fixture
def mock_k8s_client():
    c = MagicMock()
    c.namespace = "default"
    c.connected = True
    c.core = MagicMock()
    c.apps = MagicMock()
    c._api_client = MagicMock()
    return c


@pytest.fixture
def ops(mock_k8s_client):
    from k8s.operations import K8sOperations
    return K8sOperations(mock_k8s_client)
