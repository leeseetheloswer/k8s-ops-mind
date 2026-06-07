"""
Claude tool definitions for Kubernetes operations.
Each entry maps to a method in K8sOperations.
"""

TOOLS: list[dict] = [
    {
        "name": "get_pods",
        "description": "列出指定命名空间下的所有 Pod 及其状态",
        "input_schema": {
            "type": "object",
            "properties": {
                "namespace": {
                    "type": "string",
                    "description": "命名空间，不填则使用默认命名空间",
                },
            },
        },
    },
    {
        "name": "get_deployments",
        "description": "列出指定命名空间下的所有 Deployment 及其副本状态",
        "input_schema": {
            "type": "object",
            "properties": {
                "namespace": {"type": "string", "description": "命名空间"},
            },
        },
    },
    {
        "name": "get_services",
        "description": "列出指定命名空间下的所有 Service",
        "input_schema": {
            "type": "object",
            "properties": {
                "namespace": {"type": "string", "description": "命名空间"},
            },
        },
    },
    {
        "name": "get_nodes",
        "description": "列出集群所有节点及其状态",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_events",
        "description": "获取指定命名空间下的集群事件，常用于排查异常",
        "input_schema": {
            "type": "object",
            "properties": {
                "namespace": {"type": "string", "description": "命名空间"},
            },
        },
    },
    {
        "name": "describe_resource",
        "description": "查看某个 K8s 资源的详细信息（类似 kubectl describe）",
        "input_schema": {
            "type": "object",
            "properties": {
                "kind":      {"type": "string", "description": "资源类型，如 Pod、Deployment、Service"},
                "name":      {"type": "string", "description": "资源名称"},
                "namespace": {"type": "string", "description": "命名空间"},
            },
            "required": ["kind", "name"],
        },
    },
    {
        "name": "get_logs",
        "description": "获取 Pod 的日志。CrashLoopBackOff 场景下建议先用 previous=true 获取上一次崩溃的日志，比当前日志更能定位崩溃原因。",
        "input_schema": {
            "type": "object",
            "properties": {
                "pod_name":   {"type": "string",  "description": "Pod 名称"},
                "namespace":  {"type": "string",  "description": "命名空间"},
                "tail_lines": {"type": "integer", "description": "返回最后 N 行，默认 50"},
                "previous":   {"type": "boolean", "description": "true 则返回上一次（已崩溃）容器的日志，用于 CrashLoopBackOff 排查"},
            },
            "required": ["pod_name"],
        },
    },
    {
        "name": "scale_deployment",
        "description": "对 Deployment 进行扩缩容",
        "input_schema": {
            "type": "object",
            "properties": {
                "name":      {"type": "string",  "description": "Deployment 名称"},
                "replicas":  {"type": "integer", "description": "目标副本数"},
                "namespace": {"type": "string",  "description": "命名空间"},
            },
            "required": ["name", "replicas"],
        },
    },
    {
        "name": "apply_manifest",
        "description": "应用一段 YAML manifest（类似 kubectl apply -f）",
        "input_schema": {
            "type": "object",
            "properties": {
                "yaml_content": {"type": "string", "description": "YAML 格式的 K8s manifest 内容"},
            },
            "required": ["yaml_content"],
        },
    },
    {
        "name": "delete_resource",
        "description": "删除指定的 K8s 资源，请谨慎使用",
        "input_schema": {
            "type": "object",
            "properties": {
                "kind":      {"type": "string", "description": "资源类型"},
                "name":      {"type": "string", "description": "资源名称"},
                "namespace": {"type": "string", "description": "命名空间"},
            },
            "required": ["kind", "name"],
        },
    },
]
