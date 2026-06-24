"""Terminal rendering using Rich — mirrors ChatGPT web aesthetics."""
from __future__ import annotations

from typing import Optional

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.style import Style
from rich.text import Text
from rich.theme import Theme

PWM_THEME = Theme({
    "user_label": "bold cyan",
    "assistant_label": "bold green",
    "system_label": "bold yellow",
    "info": "dim white",
    "error": "bold red",
    "command": "bold magenta",
    "model": "bold blue",
    "token_info": "dim cyan",
})

console = Console(theme=PWM_THEME, highlight=True)
error_console = Console(stderr=True, theme=PWM_THEME)


def print_banner(model: str) -> None:
    console.print()
    banner = Text()
    banner.append("ChatGPT", style="bold white")
    banner.append(" via ", style="dim white")
    banner.append("PWM", style="bold green")
    banner.append(" · model: ", style="dim white")
    banner.append(model, style="model")
    console.print(Panel(banner, border_style="green", padding=(0, 2)))
    console.print(
        "  Type [command]/help[/command] for commands, "
        "[command]Ctrl+C[/command] or [command]/quit[/command] to exit\n",
        style="info",
    )


def print_help(model: str, system_prompt: str) -> None:
    help_text = f"""
[bold]Commands[/bold]
  [command]/clear[/command]           Clear conversation history
  [command]/save[/command]            Save conversation to disk
  [command]/load[/command]            Load a saved conversation
  [command]/history[/command]         List saved conversations
  [command]/model [name][/command]    Switch model  (current: [model]{model}[/model])
  [command]/models[/command]          List available models
  [command]/system [prompt][/command] Set system prompt
  [command]/copy[/command]            Copy last reply to clipboard
  [command]/tokens[/command]          Show token usage for this session
  [command]/login[/command]           Sign in with your ChatGPT account
  [command]/logout[/command]          Sign out
  [command]/whoami[/command]          Show signed-in account
  [command]/quit[/command]            Exit

[bold]Tips[/bold]
  • Multiline: end a line with \\ to continue on the next line
  • Up/Down arrows: navigate input history
  • Paste large code blocks — they render with syntax highlighting
"""
    console.print(Panel(help_text.strip(), title="[bold]Help[/bold]", border_style="dim"))


def print_user(text: str) -> None:
    console.print(f"\n[user_label]You[/user_label]")
    console.print(Text(text, style="white"))


def print_assistant_start(model: str) -> None:
    console.print(f"\n[assistant_label]ChatGPT[/assistant_label] [info]({model})[/info]")


def print_assistant_stream_chunk(chunk: str) -> None:
    console.print(chunk, end="", markup=False, highlight=False)


def print_assistant_full(text: str, render_markdown: bool = True) -> None:
    console.print(f"\n[assistant_label]ChatGPT[/assistant_label]")
    if render_markdown:
        console.print(Markdown(text, code_theme="monokai"))
    else:
        console.print(text)


def print_stream_end() -> None:
    console.print()


def print_token_usage(prompt: int, completion: int, total: int) -> None:
    console.print(
        f"  [token_info]tokens: {prompt} prompt + {completion} completion = {total} total[/token_info]"
    )


def print_system_prompt(prompt: str) -> None:
    console.print(
        Panel(
            Text(prompt, style="dim"),
            title="[system_label]System prompt[/system_label]",
            border_style="yellow",
        )
    )


def print_info(msg: str) -> None:
    console.print(f"[info]{msg}[/info]")


def print_error(msg: str) -> None:
    error_console.print(f"[error]Error:[/error] {msg}")


def print_rule(title: str = "") -> None:
    console.print(Rule(title, style="dim"))


def print_model_list(models: list[str], current: str) -> None:
    console.print("\n[bold]Available models:[/bold]")
    for m in models:
        marker = "[green]✓[/green] " if m == current else "  "
        console.print(f"  {marker}[model]{m}[/model]")
    console.print()
