"""Main CLI entry point — interactive ChatGPT session over a ChatGPT subscription."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

import click
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style as PTStyle

from . import __version__, auth, billing, subscription
from .config import (
    AVAILABLE_MODELS,
    DEFAULT_MODEL,
    DEFAULT_SYSTEM_PROMPT,
    HISTORY_DIR,
    load_config,
    save_config,
)
from .display import (
    console,
    print_assistant_start,
    print_assistant_stream_chunk,
    print_banner,
    print_billing,
    print_error,
    print_help,
    print_info,
    print_model_list,
    print_stream_end,
    print_system_prompt,
    print_token_usage,
)
from .history import list_conversations, load_conversation, save_conversation

PROMPT_HISTORY_FILE = HISTORY_DIR.parent / ".input_history"
PROMPT_STYLE = PTStyle.from_dict({"prompt": "#00bfff bold"})


def build_messages(
    conversation: List[dict],
    user_input: str,
    system_prompt: Optional[str],
) -> List[dict]:
    messages: List[dict] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.extend(conversation)
    messages.append({"role": "user", "content": user_input})
    return messages


def _get_multiline_input(session: PromptSession) -> Optional[str]:
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

    elif verb == "/login":
        _do_login()

    elif verb == "/logout":
        if auth.logout():
            print_info("Logged out.")
        else:
            print_info("No active session in chatgpt-pwm store.")

    elif verb == "/whoami":
        email = auth.account_email()
        print_info(f"Signed in as {email}" if email else "Not signed in.")

    elif verb == "/balance":
        key = billing.get_pwm_key()
        if not key:
            print_info("No PWM key set. Use /pwm-key to add one.")
        else:
            res = billing.check_balance(key)
            if res.valid and res.balance:
                print_info(f"PWM balance: {res.balance:.2f}")
            elif res.valid:
                print_info("PWM balance unavailable (platform unreachable).")
            else:
                print_error(res.reason)

    elif verb == "/pwm-key":
        if arg:
            res = billing.check_balance(arg.strip())
            if res.valid:
                billing.set_pwm_key(arg.strip())
                print_info(
                    f"PWM key saved. Balance: {res.balance:.2f}" if res.balance else "PWM key saved."
                )
            else:
                print_error(res.reason)
        else:
            _ensure_pwm_key()

    elif verb == "/copy":
        last_reply = next(
            (m["content"] for m in reversed(conversation) if m["role"] == "assistant"),
            None,
        )
        if last_reply:
            try:
                import subprocess
                subprocess.run(["xclip", "-selection", "clipboard"],
                               input=last_reply.encode(), check=True)
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


def _do_login() -> bool:
    try:
        print_info("Starting ChatGPT sign-in…")
        email = auth.login()
        print_info(f"Signed in{' as ' + email if email else ''}.")
        return True
    except auth.AuthError as e:
        print_error(str(e))
        return False


def _ensure_pwm_key() -> bool:
    """Prompt for and validate a PWM key for billing. Returns True if usable."""
    try:
        key = input("Enter your PWM key (pwm_…): ").strip()
    except (EOFError, KeyboardInterrupt):
        console.print()
        return False
    if not key:
        return False
    res = billing.check_balance(key)
    if not res.valid:
        print_error(res.reason or "Invalid PWM key.")
        return False
    billing.set_pwm_key(key)
    if res.balance:
        print_info(f"PWM key saved. Balance: {res.balance:.2f} PWM")
    else:
        print_info("PWM key saved.")
    return True


def _run_chat(
    model: Optional[str],
    system: Optional[str],
    no_stream: bool,
    load_path: Optional[str],
) -> None:
    cfg = load_config()
    active_model = model or cfg.get("model", DEFAULT_MODEL)
    active_system = system or cfg.get("system_prompt", DEFAULT_SYSTEM_PROMPT)
    streaming = not no_stream and cfg.get("stream", True)

    if not auth.is_logged_in():
        print_info("You are not signed in to a ChatGPT account.")
        if not _do_login():
            sys.exit(1)

    # PWM billing gate: usage is metered against your PWM balance.
    if not billing.has_pwm_key():
        print_info("A PWM key is required — usage is billed to your PWM balance.")
        if not _ensure_pwm_key():
            sys.exit(1)
    else:
        res = billing.check_balance(billing.get_pwm_key())
        if not res.valid:
            print_error(f"{res.reason} Set a new key with: chatgpt-pwm pwm-key")
            sys.exit(1)

    conversation: List[dict] = []
    if load_path:
        _, conversation = load_conversation(Path(load_path))
        print_info(f"Loaded {len(conversation)} messages from {load_path}")

    total_prompt_tokens = 0
    total_completion_tokens = 0

    PROMPT_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    session: PromptSession = PromptSession(history=FileHistory(str(PROMPT_HISTORY_FILE)))

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
                user_input, conversation, active_model, active_system,
                total_prompt_tokens, total_completion_tokens,
            )
            if quit_now:
                console.print("\n[info]Goodbye![/info]")
                break
            continue

        messages = build_messages(conversation, user_input, active_system)
        reply_chunks: List[str] = []
        usage = None

        try:
            print_assistant_start(active_model)
            for delta, chunk_usage in subscription.stream_chat(messages, active_model):
                if delta:
                    print_assistant_stream_chunk(delta)
                    reply_chunks.append(delta)
                if chunk_usage:
                    usage = chunk_usage
            print_stream_end()
            reply = "".join(reply_chunks)

            conversation.append({"role": "user", "content": user_input})
            conversation.append({"role": "assistant", "content": reply})

            if usage:
                total_prompt_tokens += usage.get("prompt_tokens", 0)
                total_completion_tokens += usage.get("completion_tokens", 0)
                print_token_usage(
                    usage["prompt_tokens"], usage["completion_tokens"], usage["total_tokens"]
                )
                key = billing.get_pwm_key()
                if key:
                    billed, bal_after, amount = billing.charge(
                        key, active_model,
                        usage["prompt_tokens"], usage["completion_tokens"],
                    )
                    if billed:
                        print_billing(amount, bal_after)

        except auth.AuthError as e:
            print_error(str(e))
        except subscription.UpstreamError as e:
            if e.status == 401:
                print_error("Session expired. Run /login to sign in again.")
            else:
                print_error(f"API error {e.status}: {e.body[:200]}")
        except KeyboardInterrupt:
            print_stream_end()
            print_info("(interrupted)")
            if reply_chunks:
                conversation.append({"role": "user", "content": user_input})
                conversation.append({"role": "assistant", "content": "".join(reply_chunks)})


# ── Click CLI ──────────────────────────────────────────────────────────────
@click.group(
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option("--model", "-m", default=None, help="Model to use (e.g. gpt-5.5)")
@click.option("--system", "-s", default=None, help="System prompt")
@click.option("--no-stream", is_flag=True, default=False, help="Disable streaming")
@click.option("--load", "load_path", default=None, type=click.Path(exists=True),
              help="Load conversation file")
@click.version_option(__version__, "--version", message="chatgpt-pwm %(version)s")
@click.pass_context
def main(ctx, model, system, no_stream, load_path):
    """ChatGPT CLI — powered by your ChatGPT subscription, gated by PWM.

    Sign in once with your ChatGPT account:

      chatgpt-pwm login

    Then just run `chatgpt-pwm` to chat. Generation uses your ChatGPT plan
    (the same subscription auth Codex uses) — no API key required.
    """
    if ctx.invoked_subcommand is None:
        _run_chat(model, system, no_stream, load_path)


@main.command()
def login():
    """Sign in with your ChatGPT account (OAuth)."""
    if not _do_login():
        sys.exit(1)


@main.command()
def logout():
    """Sign out and remove stored ChatGPT tokens."""
    if auth.logout():
        print_info("Logged out.")
    else:
        print_info("No active session.")


@main.command()
def whoami():
    """Show the signed-in ChatGPT account."""
    email = auth.account_email()
    print_info(f"Signed in as {email}" if email else "Not signed in. Run `chatgpt-pwm login`.")


@main.command("pwm-key")
@click.argument("key", required=False)
def pwm_key(key):
    """Set the PWM key used to bill usage (prompts if not given)."""
    if key:
        res = billing.check_balance(key.strip())
        if not res.valid:
            print_error(res.reason or "Invalid PWM key.")
            sys.exit(1)
        billing.set_pwm_key(key.strip())
        print_info(f"PWM key saved. Balance: {res.balance:.2f} PWM" if res.balance else "PWM key saved.")
    else:
        if not _ensure_pwm_key():
            sys.exit(1)


@main.command()
def balance():
    """Show your PWM token balance."""
    key = billing.get_pwm_key()
    if not key:
        print_info("No PWM key set. Run `chatgpt-pwm pwm-key`.")
        return
    res = billing.check_balance(key)
    if res.valid and res.balance:
        print_info(f"PWM balance: {res.balance:.2f}")
    elif res.valid:
        print_info("PWM balance unavailable (platform unreachable).")
    else:
        print_error(res.reason)
