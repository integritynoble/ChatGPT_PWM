"""Main CLI entry point — interactive ChatGPT session."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

import click
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style as PTStyle

from . import __version__
from .chat import build_client, build_messages, complete_response, stream_response
from .config import (
    AVAILABLE_MODELS,
    DEFAULT_MODEL,
    DEFAULT_SYSTEM_PROMPT,
    HISTORY_DIR,
    get_api_key,
    get_base_url,
    load_config,
    save_config,
)
from .display import (
    console,
    print_assistant_full,
    print_assistant_start,
    print_assistant_stream_chunk,
    print_banner,
    print_error,
    print_help,
    print_info,
    print_model_list,
    print_rule,
    print_stream_end,
    print_system_prompt,
    print_token_usage,
    print_user,
)
from .history import list_conversations, load_conversation, save_conversation


PROMPT_HISTORY_FILE = HISTORY_DIR.parent / ".input_history"
PROMPT_STYLE = PTStyle.from_dict({"prompt": "#00bfff bold"})


def _get_multiline_input(session: PromptSession) -> Optional[str]:
    """Collect possibly multi-line input. Lines ending with \\ continue."""
    lines: List[str] = []
    while True:
        try:
            text = session.prompt("You: ", style=PROMPT_STYLE)
        except (EOFError, KeyboardInterrupt):
            return None
        if text.endswith("\\"):
            lines.append(text[:-1])
            continue
        lines.append(text)
        break
    return "\n".join(lines).strip()


def _handle_command(
    cmd: str,
    conversation: List[dict],
    model: str,
    system_prompt: str,
    total_prompt_tokens: int,
    total_completion_tokens: int,
) -> tuple[List[dict], str, str, bool]:
    """
    Returns (conversation, model, system_prompt, should_quit).
    """
    parts = cmd.strip().split(None, 1)
    verb = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if verb in ("/quit", "/exit", "/q"):
        return conversation, model, system_prompt, True

    elif verb == "/help":
        print_help(model, system_prompt)

    elif verb == "/clear":
        conversation = []
        print_info("Conversation cleared.")

    elif verb == "/save":
        path = save_conversation(conversation)
        print_info(f"Saved to {path}")

    elif verb == "/history":
        convs = list_conversations()
        if not convs:
            print_info("No saved conversations.")
        else:
            console.print("\n[bold]Saved conversations:[/bold]")
            for i, p in enumerate(convs[:20], 1):
                console.print(f"  [dim]{i:2}.[/dim] {p.name}")
            console.print()

    elif verb == "/load":
        convs = list_conversations()
        if not convs:
            print_info("No saved conversations.")
        else:
            if arg.isdigit():
                idx = int(arg) - 1
            else:
                console.print("\n[bold]Saved conversations:[/bold]")
                for i, p in enumerate(convs[:20], 1):
                    console.print(f"  {i:2}. {p.name}")
                raw = input("\nEnter number: ").strip()
                idx = int(raw) - 1 if raw.isdigit() else -1
            if 0 <= idx < len(convs):
                title, conversation = load_conversation(convs[idx])
                print_info(f"Loaded: {title} ({len(conversation)} messages)")
            else:
                print_error("Invalid selection.")

    elif verb == "/model":
        if arg:
            if arg in AVAILABLE_MODELS:
                model = arg
                cfg = load_config()
                cfg["model"] = model
                save_config(cfg)
                print_info(f"Model set to {model}")
            else:
                print_error(f"Unknown model '{arg}'. Use /models to list.")
        else:
            print_info(f"Current model: {model}")

    elif verb == "/models":
        print_model_list(AVAILABLE_MODELS, model)

    elif verb == "/system":
        if arg:
            system_prompt = arg
            cfg = load_config()
            cfg["system_prompt"] = system_prompt
            save_config(cfg)
            print_info("System prompt updated.")
        else:
            print_system_prompt(system_prompt)

    elif verb == "/tokens":
        total = total_prompt_tokens + total_completion_tokens
        print_token_usage(total_prompt_tokens, total_completion_tokens, total)

    elif verb == "/copy":
        last_reply = next(
            (m["content"] for m in reversed(conversation) if m["role"] == "assistant"),
            None,
        )
        if last_reply:
            try:
                import subprocess
                p = subprocess.run(["xclip", "-selection", "clipboard"], input=last_reply.encode(), check=True)
                print_info("Copied to clipboard.")
            except Exception:
                try:
                    import subprocess
                    subprocess.run(["pbcopy"], input=last_reply.encode(), check=True)
                    print_info("Copied to clipboard.")
                except Exception:
                    print_error("Clipboard not available. Install xclip or use pbcopy (macOS).")
        else:
            print_info("No assistant reply to copy.")

    else:
        print_error(f"Unknown command '{verb}'. Type /help for help.")

    return conversation, model, system_prompt, False


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--model", "-m", default=None, help="Model to use (e.g. gpt-4o)")
@click.option("--system", "-s", default=None, help="System prompt")
@click.option("--no-stream", is_flag=True, default=False, help="Disable streaming")
@click.option("--api-key", envvar="OPENAI_API_KEY", default=None, help="API key")
@click.option("--base-url", envvar="OPENAI_BASE_URL", default=None, help="Override API base URL")
@click.option("--load", "load_path", default=None, type=click.Path(exists=True), help="Load conversation file")
@click.option("--version", is_flag=True, is_eager=True, expose_value=False,
              callback=lambda ctx, _, v: (click.echo(f"chatgpt-pwm {__version__}"), ctx.exit()) if v else None,
              help="Show version")
def main(
    model: Optional[str],
    system: Optional[str],
    no_stream: bool,
    api_key: Optional[str],
    base_url: Optional[str],
    load_path: Optional[str],
) -> None:
    """ChatGPT CLI — powered by PWM tokens.\n
    Set your PWM token as the API key:\n
      export OPENAI_API_KEY=pwm_your_key_here\n
    The tool connects to https://physicsworldmodel.org/api/v1/exchange/openai
    which routes your request through the PWM exchange to OpenAI.
    """
    cfg = load_config()
    active_model = model or cfg.get("model", DEFAULT_MODEL)
    active_system = system or cfg.get("system_prompt", DEFAULT_SYSTEM_PROMPT)
    streaming = not no_stream and cfg.get("stream", True)
    resolved_base_url = base_url or get_base_url()

    try:
        client = build_client(api_key=api_key, base_url=resolved_base_url)
    except ValueError as e:
        print_error(str(e))
        sys.exit(1)

    conversation: List[dict] = []
    if load_path:
        _, conversation = load_conversation(Path(load_path))
        print_info(f"Loaded {len(conversation)} messages from {load_path}")

    total_prompt_tokens = 0
    total_completion_tokens = 0

    PROMPT_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    session: PromptSession = PromptSession(
        history=FileHistory(str(PROMPT_HISTORY_FILE))
    )

    print_banner(active_model)

    while True:
        try:
            user_input = _get_multiline_input(session)
        except KeyboardInterrupt:
            console.print("\n[info]Use /quit to exit.[/info]")
            continue

        if user_input is None:
            console.print("\n[info]Goodbye![/info]")
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            conversation, active_model, active_system, quit_now = _handle_command(
                user_input,
                conversation,
                active_model,
                active_system,
                total_prompt_tokens,
                total_completion_tokens,
            )
            if quit_now:
                console.print("\n[info]Goodbye![/info]")
                break
            continue

        messages = build_messages(conversation, user_input, active_system)

        try:
            print_assistant_start(active_model)
            reply_chunks: List[str] = []
            usage = None

            if streaming:
                for chunk, chunk_usage in stream_response(client, messages, active_model):
                    if chunk:
                        print_assistant_stream_chunk(chunk)
                        reply_chunks.append(chunk)
                    if chunk_usage:
                        usage = chunk_usage
                print_stream_end()
                reply = "".join(reply_chunks)
            else:
                reply, usage = complete_response(client, messages, active_model)
                print_assistant_full(reply)

            conversation.append({"role": "user", "content": user_input})
            conversation.append({"role": "assistant", "content": reply})

            if usage:
                total_prompt_tokens += usage.get("prompt_tokens", 0)
                total_completion_tokens += usage.get("completion_tokens", 0)
                print_token_usage(
                    usage["prompt_tokens"],
                    usage["completion_tokens"],
                    usage["total_tokens"],
                )

        except openai.AuthenticationError:
            print_error(
                "Authentication failed. Check your PWM token:\n"
                "  export OPENAI_API_KEY=pwm_your_key_here"
            )
        except openai.RateLimitError:
            print_error("Rate limit or insufficient PWM token balance.")
        except openai.APIConnectionError as e:
            print_error(f"Connection error: {e}")
        except openai.APIStatusError as e:
            print_error(f"API error {e.status_code}: {e.message}")
        except KeyboardInterrupt:
            print_stream_end()
            print_info("(interrupted)")
            if reply_chunks:
                conversation.append({"role": "user", "content": user_input})
                conversation.append({"role": "assistant", "content": "".join(reply_chunks)})
