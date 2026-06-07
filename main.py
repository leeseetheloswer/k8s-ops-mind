"""
K8s Ops Agent — interactive CLI entry point.
"""
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from config.settings import settings
from k8s.client import K8sClient
from k8s.operations import K8sOperations
from agent.factory import create_agent
from utils.logger import get_logger

logger = get_logger(__name__)
console = Console()

BANNER = """[bold cyan]K8s 运维助手[/bold cyan]  provider=[yellow]{provider}[/yellow]
输入你的问题，助手将调用集群工具帮你完成运维任务。
输入 [bold]exit[/bold] 或 [bold]quit[/bold] 退出，输入 [bold]reset[/bold] 清空对话历史。"""


def main() -> None:
    console.print(Panel(BANNER.format(provider=settings.llm_provider), expand=False))

    # Initialize K8s client & operations
    k8s_client = K8sClient(
        kubeconfig=settings.kubeconfig,
        namespace=settings.k8s_namespace,
    )
    k8s_client.connect()
    ops = K8sOperations(k8s_client)

    # Initialize agent (provider determined by LLM_PROVIDER in .env)
    agent = create_agent(ops)

    while True:
        try:
            user_input = Prompt.ask("\n[bold green]你[/bold green]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]已退出。[/dim]")
            break

        if not user_input:
            continue

        if user_input.lower() in {"exit", "quit"}:
            console.print("[dim]再见！[/dim]")
            break

        if user_input.lower() == "reset":
            agent.reset()
            console.print("[dim]对话历史已清空。[/dim]")
            continue

        with console.status("[bold yellow]助手思考中...[/bold yellow]"):
            reply = agent.chat(user_input)

        console.print(Panel(reply, title="[bold blue]助手[/bold blue]", expand=False))


if __name__ == "__main__":
    main()
