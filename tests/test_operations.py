import pytest
from unittest.mock import MagicMock, patch
from kubernetes.client.rest import ApiException

from tests.conftest import (
    make_pod, make_deployment, make_service, make_node, make_event
)


class TestGetPods:
    def test_returns_pod_list(self, ops, mock_k8s_client):
        mock_k8s_client.core.list_namespaced_pod.return_value.items = [
            make_pod("nginx-abc", ready=True, restarts=0),
            make_pod("redis-xyz", ready=False, restarts=2),
        ]
        result = ops.get_pods()
        assert len(result) == 2
        assert result[0]["name"] == "nginx-abc"
        assert result[0]["ready"] == "1/1"
        assert result[0]["restarts"] == 0
        assert result[1]["restarts"] == 2

    def test_uses_default_namespace(self, ops, mock_k8s_client):
        mock_k8s_client.core.list_namespaced_pod.return_value.items = []
        ops.get_pods()
        mock_k8s_client.core.list_namespaced_pod.assert_called_once_with(namespace="default")

    def test_uses_given_namespace(self, ops, mock_k8s_client):
        mock_k8s_client.core.list_namespaced_pod.return_value.items = []
        ops.get_pods(namespace="kube-system")
        mock_k8s_client.core.list_namespaced_pod.assert_called_once_with(namespace="kube-system")

    def test_api_exception_returns_error(self, ops, mock_k8s_client):
        mock_k8s_client.core.list_namespaced_pod.side_effect = ApiException(status=403)
        result = ops.get_pods()
        assert len(result) == 1
        assert "error" in result[0]


class TestGetDeployments:
    def test_returns_deployment_list(self, ops, mock_k8s_client):
        mock_k8s_client.apps.list_namespaced_deployment.return_value.items = [
            make_deployment("nginx", replicas=3, ready=3),
        ]
        result = ops.get_deployments()
        assert result[0]["name"] == "nginx"
        assert result[0]["desired"] == 3
        assert result[0]["ready"] == 3

    def test_api_exception_returns_error(self, ops, mock_k8s_client):
        mock_k8s_client.apps.list_namespaced_deployment.side_effect = ApiException(status=500)
        result = ops.get_deployments()
        assert "error" in result[0]


class TestGetServices:
    def test_returns_service_list(self, ops, mock_k8s_client):
        mock_k8s_client.core.list_namespaced_service.return_value.items = [
            make_service("nginx-svc", port=80),
        ]
        result = ops.get_services()
        assert result[0]["name"] == "nginx-svc"
        assert result[0]["type"] == "ClusterIP"
        assert "80" in result[0]["ports"][0]

    def test_api_exception_returns_error(self, ops, mock_k8s_client):
        mock_k8s_client.core.list_namespaced_service.side_effect = ApiException(status=500)
        result = ops.get_services()
        assert "error" in result[0]


class TestGetNodes:
    def test_returns_node_list(self, ops, mock_k8s_client):
        mock_k8s_client.core.list_node.return_value.items = [
            make_node("node-1", ready=True),
            make_node("node-2", ready=False),
        ]
        result = ops.get_nodes()
        assert result[0]["status"] == "Ready"
        assert result[1]["status"] == "NotReady"
        assert "control-plane" in result[0]["roles"]

    def test_api_exception_returns_error(self, ops, mock_k8s_client):
        mock_k8s_client.core.list_node.side_effect = ApiException(status=500)
        result = ops.get_nodes()
        assert "error" in result[0]


class TestGetEvents:
    def test_returns_events_sorted_by_time(self, ops, mock_k8s_client):
        ev1 = make_event("Normal", "Pulled", count=1)
        ev1.last_timestamp = "2026-01-01T00:00:00Z"
        ev2 = make_event("Warning", "BackOff", count=5)
        ev2.last_timestamp = "2026-01-01T00:02:00Z"
        mock_k8s_client.core.list_namespaced_event.return_value.items = [ev1, ev2]
        result = ops.get_events()
        # 最新的排在前面
        assert result[0]["reason"] == "BackOff"
        assert result[1]["reason"] == "Pulled"

    def test_api_exception_returns_error(self, ops, mock_k8s_client):
        mock_k8s_client.core.list_namespaced_event.side_effect = ApiException(status=500)
        result = ops.get_events()
        assert "error" in result[0]


class TestGetLogs:
    def test_returns_log_string(self, ops, mock_k8s_client):
        mock_k8s_client.core.read_namespaced_pod_log.return_value = "line1\nline2\n"
        result = ops.get_logs("nginx-abc")
        assert "line1" in result
        mock_k8s_client.core.read_namespaced_pod_log.assert_called_once_with(
            name="nginx-abc", namespace="default", tail_lines=50, previous=False
        )

    def test_custom_tail_lines(self, ops, mock_k8s_client):
        mock_k8s_client.core.read_namespaced_pod_log.return_value = ""
        ops.get_logs("nginx-abc", tail_lines=100)
        mock_k8s_client.core.read_namespaced_pod_log.assert_called_once_with(
            name="nginx-abc", namespace="default", tail_lines=100, previous=False
        )

    def test_previous_flag_passed_through(self, ops, mock_k8s_client):
        mock_k8s_client.core.read_namespaced_pod_log.return_value = "crash log"
        result = ops.get_logs("crash-pod", previous=True)
        assert result == "crash log"
        mock_k8s_client.core.read_namespaced_pod_log.assert_called_once_with(
            name="crash-pod", namespace="default", tail_lines=50, previous=True
        )

    def test_api_exception_returns_error_string(self, ops, mock_k8s_client):
        mock_k8s_client.core.read_namespaced_pod_log.side_effect = ApiException(status=404)
        result = ops.get_logs("not-exist")
        assert result.startswith("Error:")


class TestDescribeResource:
    def test_describe_pod(self, ops, mock_k8s_client):
        pod = make_pod()
        pod.to_dict.return_value = {"kind": "Pod", "metadata": {"name": "nginx-abc"}}
        mock_k8s_client.core.read_namespaced_pod.return_value = pod
        result = ops.describe_resource("Pod", "nginx-abc")
        assert result["kind"] == "Pod"

    def test_describe_deployment(self, ops, mock_k8s_client):
        dep = make_deployment()
        dep.to_dict.return_value = {"kind": "Deployment"}
        mock_k8s_client.apps.read_namespaced_deployment.return_value = dep
        result = ops.describe_resource("Deployment", "nginx")
        assert result["kind"] == "Deployment"

    def test_unsupported_kind_returns_error(self, ops):
        result = ops.describe_resource("CronJob", "my-job")
        assert "error" in result

    def test_api_exception_returns_error(self, ops, mock_k8s_client):
        mock_k8s_client.core.read_namespaced_pod.side_effect = ApiException(status=404)
        result = ops.describe_resource("Pod", "not-exist")
        assert "error" in result


class TestScaleDeployment:
    def test_scale_success(self, ops, mock_k8s_client):
        result = ops.scale_deployment("nginx", replicas=3)
        assert result["success"] is True
        assert result["replicas"] == 3
        mock_k8s_client.apps.patch_namespaced_deployment_scale.assert_called_once()

    def test_scale_api_exception(self, ops, mock_k8s_client):
        mock_k8s_client.apps.patch_namespaced_deployment_scale.side_effect = ApiException(status=404)
        result = ops.scale_deployment("not-exist", replicas=1)
        assert result["success"] is False
        assert "error" in result


class TestDeleteResource:
    def test_delete_pod(self, ops, mock_k8s_client):
        result = ops.delete_resource("Pod", "nginx-abc")
        assert result["success"] is True
        mock_k8s_client.core.delete_namespaced_pod.assert_called_once_with(
            name="nginx-abc", namespace="default"
        )

    def test_delete_deployment(self, ops, mock_k8s_client):
        result = ops.delete_resource("Deployment", "nginx")
        assert result["success"] is True
        mock_k8s_client.apps.delete_namespaced_deployment.assert_called_once()

    def test_delete_unsupported_kind(self, ops):
        result = ops.delete_resource("StatefulSet", "my-app")
        assert result["success"] is False

    def test_delete_api_exception(self, ops, mock_k8s_client):
        mock_k8s_client.core.delete_namespaced_pod.side_effect = ApiException(status=404)
        result = ops.delete_resource("Pod", "not-exist")
        assert result["success"] is False
