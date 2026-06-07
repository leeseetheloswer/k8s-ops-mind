DANGEROUS_TOOLS: dict = {
    "delete_resource": lambda inp: (
        f"删除 {inp.get('kind', '资源')} "
        f"{inp.get('name', '')}"
        f"（namespace: {inp.get('namespace', 'default')}）"
    ),
    "scale_deployment": lambda inp: (
        f"将 Deployment {inp.get('name', '')} 副本数调整为 "
        f"{inp.get('replicas', '?')}"
        f"（namespace: {inp.get('namespace', 'default')}）"
    ),
    "apply_manifest": lambda _: "应用 YAML Manifest（可能创建或覆盖集群资源）",
}


class ConfirmationRequired(Exception):
    """Raised when a dangerous tool call needs explicit user confirmation."""

    def __init__(self, tool_name: str, tool_input: dict, tool_id: str, description: str,
                 assistant_msg=None):
        self.tool_name = tool_name
        self.tool_input = tool_input
        self.tool_id = tool_id
        self.description = description
        # The assistant message that was rolled back from history before raising.
        # execute_confirmed() must re-append it before adding the tool result.
        self.assistant_msg = assistant_msg
