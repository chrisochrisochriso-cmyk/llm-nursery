#!/usr/bin/env python3
"""
paperknight AI - pk CLI

Usage:
  pk ask "question"
  pk review <file>
  pk scan <file>
  pk status

  # Piping (chriso workflow):
  cat exploit.cpp | pk review
  git diff | pk review
  kubectl get pod -o yaml | pk scan
  echo "question" | pk ask

  --json   machine-readable output
  --quiet  plain text, no colour (for piping)
"""

import json
import os
import sys
from pathlib import Path
from typing import Optional

import httpx
import typer
import yaml
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from rag import add_command, search_command
from chat import chat_command, history_command

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
app = typer.Typer(
    name="pk",
    help="paperknight AI - your private AI on ZimaBoard",
    add_completion=False,
)
console = Console()
err_console = Console(stderr=True)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PROFILE_PATH = Path.home() / ".pk" / "profile.yaml"
DEFAULT_COORDINATOR = "http://localhost:30800"  # NodePort default


def load_profile() -> dict:
    """Load user profile from ~/.pk/profile.yaml"""
    if PROFILE_PATH.exists():
        try:
            with open(PROFILE_PATH) as f:
                return yaml.safe_load(f) or {}
        except Exception:
            pass
    return {}


def get_coordinator_url() -> str:
    profile = load_profile()
    return (
        os.environ.get("PK_COORDINATOR_URL")
        or profile.get("coordinator_url")
        or DEFAULT_COORDINATOR
    )


def get_profile_name() -> str:
    profile = load_profile()
    return profile.get("name", "default")


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

SEVERITY_COLOURS = {
    "CRITICAL": "bold red",
    "HIGH": "red",
    "MEDIUM": "yellow",
    "LOW": "cyan",
}


def stream_response(
    response: httpx.Response,
    quiet: bool = False,
    json_output: bool = False,
    thinking_msg: str = "Thinking",
) -> str:
    """Collect streamed response, show spinner, print full result."""
    full_text = []

    if json_output:
        for chunk in response.iter_text():
            full_text.append(chunk)
        result = "".join(full_text)
        print(json.dumps({"response": result}))
        return result

    if quiet:
        for chunk in response.iter_text():
            print(chunk, end="", flush=True)
            full_text.append(chunk)
        print()
        return "".join(full_text)

    # Collect silently while showing spinner
    with console.status(f"[dim]{thinking_msg}...[/dim]", spinner="dots"):
        for chunk in response.iter_text():
            full_text.append(chunk)

    result = "".join(full_text)
    console.print()
    console.print(Markdown(result))
    console.print()
    return result


def print_error(msg: str, quiet: bool = False) -> None:
    if quiet:
        print(f"ERROR: {msg}", file=sys.stderr)
    else:
        err_console.print(f"[red]ERROR:[/red] {msg}")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@app.command()
def ask(
    question: Optional[str] = typer.Argument(None, help="Question to ask"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Plain text output for piping"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
):
    """Ask paperknight AI a question. Supports piping: echo 'q' | pk ask"""
    # Read from stdin if no argument and stdin is a pipe
    if question is None:
        if not sys.stdin.isatty():
            question = sys.stdin.read().strip()
        else:
            print_error("Provide a question or pipe input", quiet)
            raise typer.Exit(1)

    coordinator = get_coordinator_url()
    profile = get_profile_name()

    try:
        with httpx.Client(timeout=600.0, verify=False) as client:
            with client.stream(
                "POST",
                f"{coordinator}/ask",
                json={"message": question, "profile": profile, "stream": True},
            ) as resp:
                if resp.status_code != 200:
                    print_error(f"Coordinator error: {resp.status_code}", quiet)
                    raise typer.Exit(1)
                stream_response(resp, quiet=quiet, json_output=json_output, thinking_msg="Thinking")

    except httpx.ConnectError:
        print_error(
            f"Cannot reach coordinator at {coordinator}\n"
            "Is paperknight AI running? Try: pk status",
            quiet,
        )
        raise typer.Exit(1)


@app.command()
def review(
    file: Optional[str] = typer.Argument(None, help="File to review (or pipe content)"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
    json_output: bool = typer.Option(False, "--json"),
):
    """Security code review. Supports piping: cat file.cpp | pk review"""
    # Read file or stdin
    if file is not None:
        filepath = Path(file)
        if not filepath.exists():
            print_error(f"File not found: {file}", quiet)
            raise typer.Exit(1)
        content = filepath.read_text()
        filename = file
    elif not sys.stdin.isatty():
        content = sys.stdin.read()
        filename = "stdin"
    else:
        print_error("Provide a file path or pipe content", quiet)
        raise typer.Exit(1)

    coordinator = get_coordinator_url()
    profile = get_profile_name()

    if not quiet and not json_output:
        console.print(f"[dim]Reviewing: {filename}[/dim]")

    try:
        with httpx.Client(timeout=600.0, verify=False) as client:
            with client.stream(
                "POST",
                f"{coordinator}/review",
                json={
                    "content": content,
                    "filename": filename,
                    "profile": profile,
                    "stream": True,
                },
            ) as resp:
                if resp.status_code != 200:
                    print_error(f"Coordinator error: {resp.status_code}", quiet)
                    raise typer.Exit(1)
                stream_response(resp, quiet=quiet, json_output=json_output, thinking_msg="Reviewing code")

    except httpx.ConnectError:
        print_error(f"Cannot reach coordinator at {coordinator}", quiet)
        raise typer.Exit(1)


@app.command()
def scan(
    file: Optional[str] = typer.Argument(None, help="File to scan (or pipe content)"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
    json_output: bool = typer.Option(False, "--json"),
):
    """Security scan with CRITICAL/HIGH/MEDIUM/LOW severity ratings."""
    if file is not None:
        filepath = Path(file)
        if not filepath.exists():
            print_error(f"File not found: {file}", quiet)
            raise typer.Exit(1)
        content = filepath.read_text()
        filename = file
    elif not sys.stdin.isatty():
        content = sys.stdin.read()
        filename = "stdin"
    else:
        print_error("Provide a file path or pipe content", quiet)
        raise typer.Exit(1)

    coordinator = get_coordinator_url()
    profile = get_profile_name()

    if not quiet and not json_output:
        console.print(f"[dim]Scanning: {filename}[/dim]")

    try:
        with httpx.Client(timeout=600.0, verify=False) as client:
            with client.stream(
                "POST",
                f"{coordinator}/scan",
                json={
                    "content": content,
                    "filename": filename,
                    "profile": profile,
                    "stream": True,
                },
            ) as resp:
                if resp.status_code != 200:
                    print_error(f"Coordinator error: {resp.status_code}", quiet)
                    raise typer.Exit(1)
                stream_response(resp, quiet=quiet, json_output=json_output, thinking_msg="Scanning for vulnerabilities")

    except httpx.ConnectError:
        print_error(f"Cannot reach coordinator at {coordinator}", quiet)
        raise typer.Exit(1)


@app.command()
def status(
    json_output: bool = typer.Option(False, "--json"),
):
    """Show paperknight AI cluster health dashboard."""
    coordinator = get_coordinator_url()
    profile = load_profile()
    username = profile.get("name", "unknown")

    try:
        with httpx.Client(timeout=10.0, verify=False) as client:
            resp = client.get(f"{coordinator}/status")
            if resp.status_code != 200:
                print_error(f"Coordinator returned {resp.status_code}")
                raise typer.Exit(1)
            data = resp.json()

    except httpx.ConnectError:
        if json_output:
            print(json.dumps({"status": "offline", "coordinator": coordinator}))
        else:
            err_console.print(
                Panel(
                    f"[red]Cannot reach coordinator[/red]\n{coordinator}\n\n"
                    "Check: kubectl get pods -n paperknight-ai",
                    title="paperknight AI - OFFLINE",
                    border_style="red",
                )
            )
        raise typer.Exit(1)

    if json_output:
        print(json.dumps(data, indent=2))
        return

    # Rich dashboard
    def node_indicator(s: str) -> str:
        return "[green]✓[/green]" if s == "ready" else "[red]✗[/red]"

    def rag_indicator(s: str) -> str:
        return "[green]✓[/green]" if s == "ok" else "[red]✗[/red]"

    model = data.get("model", "unknown")
    ollama = data.get("ollama", "unknown")
    rag = data.get("rag", "unknown")
    rag_docs = data.get("rag_documents", "?")
    history = data.get("history_today", 0)

    ollama_ok = ollama == "ready"

    lines = [
        f" Model        {model:<20} {'[green]✓[/green]' if ollama_ok else '[red]✗[/red]'}",
        f" Ollama       {'Ready' if ollama_ok else ollama:<20} {'[green]✓[/green]' if ollama_ok else '[red]✗[/red]'}",
        f" Coordinator  Running                [green]✓[/green]",
        f" RAG          {rag_docs} documents         {rag_indicator(rag)}",
        f" Queries      {history} today",
    ]

    panel_content = "\n".join(lines)
    console.print(
        Panel(
            panel_content,
            title=f"[bold]paperknight AI - {username}[/bold]",
            border_style="green" if ollama_ok else "red",
        )
    )


@app.command()
def profile(
    name: Optional[str] = typer.Argument(None, help="Set your name (chriso or johno)"),
    coordinator_url: Optional[str] = typer.Option(None, "--coordinator", help="Set full coordinator URL"),
    cluster_ip: Optional[str] = typer.Option(
        None, "--cluster-ip",
        help="Set cluster IP (LAN or Tailscale 100.x.x.x) - builds URL automatically",
    ),
):
    """View or edit your user profile (~/.pk/profile.yaml).

    Switch between local and remote access:

      pk profile --cluster-ip 192.168.1.50    # GMKtec on LAN
    """
    current = load_profile()

    if name is None and coordinator_url is None and cluster_ip is None:
        # View mode
        url = current.get("coordinator_url", DEFAULT_COORDINATOR)
        console.print(Panel(
            f"Name:            {current.get('name', 'not set')}\n"
            f"Coordinator URL: {url}\n"
            f"Profile path:    {PROFILE_PATH}\n\n"
            "[dim]Change server:  pk profile --cluster-ip <ip>[/dim]",
            title="paperknight AI - Profile",
        ))
        return

    # Update mode
    if name:
        current["name"] = name

    if cluster_ip:
        ip = cluster_ip.replace("http://", "").replace("https://", "").split(":")[0]
        current["coordinator_url"] = f"http://{ip}:30800"
        console.print(f"[cyan]Connecting to:[/cyan] {ip}")

    if coordinator_url:
        current["coordinator_url"] = coordinator_url

    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PROFILE_PATH, "w") as f:
        yaml.dump(current, f)

    console.print(f"[green]Profile saved:[/green] {PROFILE_PATH}")
    console.print(f"[dim]Coordinator: {current.get('coordinator_url')}[/dim]")


# Register RAG and chat commands from their modules
app.command(name="add")(add_command)
app.command(name="search")(search_command)
app.command(name="chat")(chat_command)
app.command(name="history")(history_command)


def main():
    app()


if __name__ == "__main__":
    main()
