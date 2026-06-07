# 故障构造与功能验证指南

本文档描述如何在本地 k3d 集群中构造真实故障场景，用于验证以下功能：

- **巡检（Inspector）**：自动检测异常并推送告警到前端
- **日志分析**：`get_logs` 预处理 + `previous=true` 崩溃日志
- **故障知识库（KB）**：自动提取诊断案例 + 检索注入上下文

前置条件：已按照 [k3d-dev-setup.md](k3d-dev-setup.md) 搭好本地集群，后端和前端均已启动。

---

## 场景一：Pod 高重启（CrashLoopBackOff）

验证：巡检告警 + `previous=true` 日志 + KB 存储

### 1. 构造故障

```bash
# 部署一个会立刻崩溃的 Pod（exit 1）
kubectl apply -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: crash-demo
  namespace: default
spec:
  containers:
  - name: app
    image: busybox
    command: ["sh", "-c", "echo '内存不足，OOMKilled' && exit 1"]
  restartPolicy: Always
EOF
```

等待约 30 秒，Pod 会进入 CrashLoopBackOff，重启次数超过阈值（默认 3）。

### 2. 预期巡检行为

- Inspector 在下一个巡检周期（默认 60s）检测到 `high_restarts` 异常
- 前端聊天界面出现橙色告警气泡，内容包含 `crash-demo` 和 LLM 诊断结论
- 日志内控制台打印 `[Alert] Pod crash-demo 重启次数...`

### 3. 手动触发对话验证

在前端输入：

```
crash-demo 这个 Pod 一直重启，帮我看看日志
```

Agent 应调用 `get_logs(pod_name="crash-demo", previous=true)` 获取崩溃前的日志，返回"内存不足，OOMKilled"字样及处置建议。

### 4. 验证知识库

对话结束后等待约 5–10 秒（后台提取），然后新开一个会话输入：

```
有个 Pod 一直 CrashLoopBackOff，怎么排查？
```

观察后端日志是否有 `KB: saved case #1`，新会话回复顶部是否出现"历史案例参考"块。

### 5. 清理

```bash
kubectl delete pod crash-demo
```

---

## 场景二：Deployment 副本数不足（Ready < Desired）

验证：巡检检测 `deployment_not_ready` + 对话诊断

### 1. 构造故障

```bash
# 先部署一个正常的 Deployment
kubectl create deployment nginx-demo --image=nginx:latest --replicas=3

# 然后强制将镜像改为不存在的版本，触发 ImagePullBackOff
kubectl set image deployment/nginx-demo nginx=nginx:nonexistent-tag-999
```

等待约 30 秒，Deployment ready < desired。

### 2. 预期巡检行为

- 前端出现告警：`Deployment nginx-demo ready 副本数不足`
- LLM 诊断应提到镜像拉取失败，建议检查镜像 tag

### 3. 手动对话验证

```
nginx-demo 的 Deployment 有问题，帮我看看是什么原因
```

Agent 应调用 `describe_resource`，发现 `ImagePullBackOff`，并给出修复建议（恢复正确镜像）。

### 4. 清理

```bash
kubectl delete deployment nginx-demo
```

---

## 场景三：Warning 事件（节点资源不足模拟）

验证：巡检检测 Warning 类型事件

### 1. 构造故障

```bash
# 部署资源请求超出节点容量的 Pod（强制调度到不满足条件的节点）
kubectl apply -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: oom-demo
  namespace: default
spec:
  containers:
  - name: app
    image: nginx
    resources:
      requests:
        memory: "999Gi"
        cpu: "999"
EOF
```

Pod 会 Pending，同时产生 `FailedScheduling` Warning 事件。

### 2. 预期巡检行为

- Inspector 检测到 Warning 事件，推送告警到前端
- 告警摘要包含 `FailedScheduling` 或 `Insufficient memory`

### 3. 手动对话验证

```
oom-demo 这个 Pod 为什么一直 Pending？
```

### 4. 清理

```bash
kubectl delete pod oom-demo
```

---

## 场景四：Node NotReady（模拟节点故障）

验证：巡检检测 `node_not_ready`

> **注意**：此操作会影响集群，谨慎在生产环境执行。k3d 本地集群安全。

### 1. 构造故障

```bash
# 停止 k3d worker 节点容器（模拟节点下线）
docker ps | grep k3d   # 找到 worker 节点容器名
docker stop <worker-container-name>
```

### 2. 预期巡检行为

- 约 60s 内前端出现节点告警：`Node <name> 状态为 NotReady`
- LLM 诊断建议检查节点 kubelet 状态

### 3. 恢复

```bash
docker start <worker-container-name>
```

---

## 场景五：日志预处理验证

验证：`filter_logs_for_llm` 信号提取 + 折叠去重

### 构造高噪音日志

```bash
kubectl apply -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: noisy-log-demo
  namespace: default
spec:
  containers:
  - name: app
    image: busybox
    command:
    - sh
    - -c
    - |
      for i in \$(seq 1 100); do echo "INFO heartbeat tick \$i"; done
      for i in \$(seq 1 50); do echo "ERROR connection refused to db:5432"; done
      echo "FATAL panic: nil pointer dereference"
      sleep 3600
EOF
```

在前端输入：

```
noisy-log-demo 的日志里有什么异常？
```

观察 Agent 实际发给 LLM 的日志是否经过了压缩（INFO 行被过滤、ERROR 重复行被折叠为"重复 N 次"，只保留 FATAL + 上下文）。可在后端日志中确认实际 token 用量明显低于全量日志。

### 清理

```bash
kubectl delete pod noisy-log-demo
```

---

## 知识库检索验证（端到端）

完成上述场景后，知识库中应已有若干案例。验证检索注入效果：

1. **重置当前会话**（点击前端"新对话"按钮）
2. 输入与之前不完全相同但语义相近的问题，例如：

   ```
   Pod 容器一直退出重启，该怎么处理？
   ```

3. 观察 Agent 回复顶部是否包含"历史案例参考"块，案例内容是否与之前诊断的 `crash-demo` 相关。

---

## 巡检参数调整（加速测试）

默认巡检间隔 60s、冷却 30 分钟，验证时可临时调小：

```bash
# .env 中修改
INSPECTOR_INTERVAL=15          # 15 秒巡检一次
INSPECTOR_COOLDOWN_MINUTES=1   # 1 分钟冷却
INSPECTOR_RESTART_THRESHOLD=2  # 重启 2 次即告警
```

修改后重启后端生效。

---

## 快速检查清单

| 功能 | 验证方法 | 预期结果 |
|------|---------|---------|
| 巡检告警推送 | 构造 CrashLoopBackOff | 前端橙色气泡出现 |
| 告警去重 | 同一 Pod 连续两个巡检周期 | 冷却期内只告警一次 |
| `previous=true` 日志 | 问 crash-demo 日志 | 显示崩溃前容器日志而非空日志 |
| 日志预处理 | noisy-log-demo 场景 | INFO 被过滤、ERROR 折叠 |
| KB 自动存储 | 对话后查后端日志 | `KB: saved case #N` |
| KB 检索注入 | 新会话问相似问题 | 回复含"历史案例参考"块 |
| 危险操作确认 | 要求删除/扩缩容 | 弹出确认弹窗 |
