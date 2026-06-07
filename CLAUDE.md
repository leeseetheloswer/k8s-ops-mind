# K8s 运维助手 Agent

## 项目背景

基于 Claude / DeepSeek API（tool use）的 Kubernetes 运维对话助手。目标是让运维人员通过自然语言完成日常 K8s 运维任务，无需记忆 kubectl 命令细节。提供 CLI 和 Web 两种使用方式。

## 技术栈

- **LLM**：支持 Anthropic Claude 和 DeepSeek，通过 `LLM_PROVIDER` 环境变量切换
- **Agent 模式**：标准 agentic loop — 模型返回 tool_use/tool_calls → 本地执行 → 追加结果 → 继续循环
- **K8s 对接**：`kubernetes` Python client，支持本地 kubeconfig 和 in-cluster 两种模式
- **Web 后端**：FastAPI，session 隔离，sync 路由跑在线程池
- **Web 前端**：React 18 + Vite，CSS Modules，支持 Markdown / 代码高亮
- **配置**：`pydantic-settings` 读取 `.env`

## 目录结构

```
k8s-ops-agent/
├── main.py                  # CLI 入口
├── server.py                # FastAPI 后端
├── run.sh                   # 一键启动 CLI
├── start-web.sh             # 一键启动 Web（前端 + 后端）
├── config/settings.py       # 统一配置（provider、API Key、kubeconfig 等）
├── utils/logger.py          # Rich 日志
├── k8s/
│   ├── client.py            # K8s 连接层（kubeconfig / in-cluster 自动选择）
│   └── operations.py        # 所有 K8s 操作的真实实现
├── agent/
│   ├── prompts.py           # 共享 SYSTEM_PROMPT
│   ├── tools.py             # Tool schema（Anthropic 格式）
│   ├── agent.py             # Anthropic Claude agent
│   ├── deepseek_agent.py    # DeepSeek agent（OpenAI-compatible，自动转换 schema）
│   └── factory.py           # create_agent()，按 LLM_PROVIDER 返回对应实例
└── frontend/
    ├── src/
    │   ├── App.jsx           # 会话管理、消息持久化（localStorage）
    │   └── components/
    │       ├── Header.jsx
    │       ├── Sidebar.jsx   # 集群信息 + 快速提问（点击直接发送）
    │       ├── ChatMessage.jsx  # Markdown + 代码高亮
    │       └── ChatInput.jsx
    └── vite.config.js        # /api 代理到 localhost:8000
```

## 当前状态

- K8s 已真实对接，支持 Pod / Deployment / Service / Node / Event / Log 的读写操作
- Web 模式：FastAPI 后端 + React 前端，消息记录持久化到 localStorage
- CLI 模式：Rich 交互终端

## 关键约定

- **新增工具**：先在 `k8s/operations.py` 加方法，再在 `agent/tools.py` 加对应 schema，名称必须一致（`_dispatch_tool` 靠方法名路由）
- **切换 provider**：只改 `.env` 中的 `LLM_PROVIDER`，代码无需改动
- **系统提示**：统一在 `agent/prompts.py` 的 `SYSTEM_PROMPT` 中维护
- **tool schema**：以 Anthropic 格式为准，`deepseek_agent.py` 在模块加载时自动转为 OpenAI function-calling 格式
- **后端 session**：内存中以 `session_id`（UUID，存在 localStorage）为 key 隔离 agent 实例；后端重启后 history 丢失，前端显示不受影响
