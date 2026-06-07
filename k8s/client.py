from kubernetes import client, config
from kubernetes.client.rest import ApiException
from utils.logger import get_logger

logger = get_logger(__name__)


class K8sClient:
    def __init__(self, kubeconfig: str, namespace: str):
        self.kubeconfig = kubeconfig
        self.namespace = namespace
        self.core: client.CoreV1Api | None = None
        self.apps: client.AppsV1Api | None = None
        self._api_client: client.ApiClient | None = None
        self._connected = False

    def connect(self) -> bool:
        try:
            # 优先尝试 in-cluster（Pod 内运行），否则读本地 kubeconfig
            try:
                config.load_incluster_config()
                logger.info("Using in-cluster config")
            except config.ConfigException:
                path = self.kubeconfig or None
                config.load_kube_config(config_file=path)
                logger.info(f"Using kubeconfig: {path or 'default'}")

            self._api_client = client.ApiClient()
            self.core = client.CoreV1Api(self._api_client)
            self.apps = client.AppsV1Api(self._api_client)
            self._connected = True
            logger.info(f"Connected to cluster (namespace={self.namespace})")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Kubernetes: {e}")
            return False

    @property
    def connected(self) -> bool:
        return self._connected
