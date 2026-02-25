"""
paperknight AI - Chat commands

pk chat     - Interactive multi-turn chat session
pk history  - View recent query history
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text

console = Console()
err_console = Console(stderr=True)


def get_coordinator_url() -> str:
    try:
        import yaml
        profile_path = Path.home() / ".pk" / "profile.yaml"
        if profile_path.exists():
            with open(profile_path) as f:
                p = yaml.safe_load(f) or {}
                return p.get("coordinator_url", "http://localhost:30800")
    except Exception:
        pass
    return "http://localhost:30800"


def get_profile_name() -> str:
    try:
        import yaml
        profile_path = Path.home() / ".pk" / "profile.yaml"
        if profile_path.exists():
            with open(profile_path) as f:
                p = yaml.safe_load(f) or {}
                return p.get("name", "default")
    except Exception:
        pass
    return "default"


def chat_command(
    quiet: bool = typer.Option(False, "--quiet", "-q", help="No colour, plain text"),
):
    """Interactive multi-turn chat with paperknight AI."""
    coordinator = get_coordinator_url()
    profile = get_profile_name()

    # Verify coordinator is reachable before starting
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.get(f"{coordinator}/health")
            if r.status_code != 200:
                err_console.print(f"[red]Coordinator unhealthy: {r.status_code}[/red]")
                raise typer.Exit(1)
    except httpx.ConnectError:
        err_console.print(
            f"[red]Cannot reach coordinator at {coordinator}[/red]\n"
            "Run: pk status"
        )
        raise typer.Exit(1)

    if not quiet:
        console.print(
            Panel(
                f"[bold]paperknight AI[/bold] - {profile}\n"
                "[dim]Type your message. Ctrl+C or 'exit' to quit.[/dim]",
                border_style="dim",
            )
        )
    else:
        print("paperknight AI chat - type 'exit' to quit")

    history: list[dict] = []  # local session history for display

    while True:
        # Prompt
        try:
            if quiet:
                sys.stdout.write("> ")
                sys.stdout.flush()
                user_input = sys.stdin.readline().strip()
            else:
                user_input = Prompt.ask(f"[bold cyan]{profile}[/bold cyan]")
        except (KeyboardInterrupt, EOFError):
            if not quiet:
                console.print("\n[dim]Session ended.[/dim]")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit", "q"):
            if not quiet:
                console.print("[dim]Session ended.[/dim]")
            break

        # Stream response
        try:
            full_response = []
            with httpx.Client(timeout=180.0) as client:
                with client.stream(
                    "POST",
                    f"{coordinator}/ask",
                    json={"message": user_input, "profile": profile, "stream": True},
                ) as resp:
                    if resp.status_code != 200:
                        err_console.print(f"[red]Error {resp.status_code}[/red]")
                        continue

                    if not quiet:
                        console.print("[dim]pk[/dim] ", end="")

                    for chunk in resp.iter_text():
                        full_response.append(chunk)
                        if quiet:
                            print(chunk, end="", flush=True)
                        else:
                            console.print(chunk, end="", markup=False)

                    print()  # newline after response

            history.append({
                "ts": datetime.now().isoformat(),
                "user": user_input,
                "assistant": "".join(full_response),
            })

            if not quiet:
                console.print()  # blank line between turns

        except httpx.ConnectError:
            err_console.print(f"[red]Lost connection to coordinator.[/red]")
            break
        except httpx.ReadTimeout:
            err_console.print("[yellow]Response timed out. Try a shorter question.[/yellow]")


def history_command(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of entries to show"),
    date: Optional[str] = typer.Option(None, "--date", help="Date (YYYY-MM-DD, default: today)"),
    json_output: bool = typer.Option(False, "--json"),
):
    """Show recent query history."""
    coordinator = get_coordinator_url()

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(f"{coordinator}/history", params={"limit": limit})
            if resp.status_code != 200:
                err_console.print(f"[red]Error {resp.status_code}[/red]")
                raise typer.Exit(1)
            data = resp.json()

    except httpx.ConnectError:
        err_console.print(f"[red]Cannot reach coordinator at {coordinator}[/red]")
        raise typer.Exit(1)

    entries = data.get("entries", [])

    if json_output:
        print(json.dumps(entries, indent=2))
        return

    if not entries:
        console.print("[dim]No history for today.[/dim]")
        return

    for entry in entries:
        ts = entry.get("ts", "")[:19].replace("T", " ")
        profile = entry.get("profile", "?")
        command = entry.get("command", "ask")
        query = entry.get("query", "")
        preview = entry.get("response_preview", "")

        console.print(
            f"[dim]{ts}[/dim] [cyan]{profile}[/cyan] [dim]{command}[/dim]"
        )
        console.print(f"  [bold]Q:[/bold] {query[:120]}")
        if preview:
            console.print(f"  [dim]A: {preview[:120]}...[/dim]")
        console.print()
