# K8s 运维助手

通过自然语言与 Kubernetes 集群对话，完成日常运维操作。

## 功能

- 查看 Pod / Deployment / Service / Node 状态
- 获取 Pod 日志与集群事件
- 扩缩容 Deployment
- 应用 YAML manifest / 删除资源
- 支持 Anthropic Claude 和 DeepSeek 两种 LLM

## 快速开始

### 1. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，选择一种 LLM provider：

```ini
# 使用 DeepSeek（推荐，价格低）
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-xxxxxxxx

# 或使用 Anthropic Claude
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-xxxxxxxx
```

确保 kubeconfig 路径正确（默认 `~/.kube/config`）：

```ini
KUBECONFIG=~/.kube/config
K8S_NAMESPACE=default
```

### 2. 启动

**Web 模式（推荐）**

```bash
./start-web.sh
```

首次运行自动安装 Python 和 Node.js 依赖。启动后访问 http://localhost:5173

**CLI 模式**

```bash
./run.sh
```

## 使用示例

```
你：列出所有 Pod
你：nginx 这个 Pod 最近的日志
你：帮我把 nginx deployment 扩容到 3 个副本
你：default 命名空间最近有哪些异常事件
你：描述一下 nginx 这个 deployment 的详情
```

## K8s 对接说明

### 本地开发

确保本机 `kubectl` 可以正常连接集群即可，程序自动读取 `~/.kube/config`：

```bash
kubectl get nodes   # 能正常返回说明连接没问题
./start-web.sh
```

### 部署到 Pod 内（in-cluster）

程序自动检测并使用 in-cluster config（ServiceAccount Token），无需 kubeconfig。

需要为 ServiceAccount 授予权限：

```bash
kubectl apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: k8s-ops-agent
rules:
- apiGroups: ["", "apps"]
  resources: ["pods", "pods/log", "deployments", "services",
              "nodes", "events", "deployments/scale"]
  verbs: ["get", "list", "watch", "create", "patch", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: k8s-ops-agent
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: k8s-ops-agent
subjects:
- kind: ServiceAccount
  name: default
  namespace: default
EOF
```

## 环境变量说明

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_PROVIDER` | `anthropic` | LLM 提供商：`anthropic` 或 `deepseek` |
| `ANTHROPIC_API_KEY` | — | Anthropic API Key（provider=anthropic 时必填） |
| `ANTHROPIC_MODEL` | `claude-opus-4-8` | Anthropic 模型名 |
| `DEEPSEEK_API_KEY` | — | DeepSeek API Key（provider=deepseek 时必填） |
| `DEEPSEEK_MODEL` | `deepseek-chat` | DeepSeek 模型名 |
| `KUBECONFIG` | `~/.kube/config` | kubeconfig 文件路径 |
| `K8S_NAMESPACE` | `default` | 默认操作的命名空间 |
| `AGENT_MAX_TOKENS` | `4096` | 单次最大 token 数 |

## 服务端口

| 服务 | 地址 |
|------|------|
| React 前端 | http://localhost:5173 |
| FastAPI 后端 | http://localhost:8000 |
| API 文档 | http://localhost:8000/docs |

## 停止服务

```bash
pkill -f uvicorn; pkill -f vite
```
