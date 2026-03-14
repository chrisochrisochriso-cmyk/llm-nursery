"""
paperknight AI - RAG commands

pk add <path>              - Add local file to knowledge base
pk add --url <url>         - Fetch URL and add to knowledge base
pk add --cve CVE-XXXX-XXXX - Fetch CVE from NVD and add
pk search "query"          - Search knowledge base (no inference)
"""

import sys
from pathlib import Path
from typing import Optional

import httpx
import typer
from rich.console import Console
from rich.table import Table

console = Console()
err_console = Console(stderr=True)

# Supported file extensions for pk add <path>
SUPPORTED_EXTENSIONS = {
    ".py", ".cpp", ".c", ".h", ".hpp", ".go", ".rs",
    ".js", ".ts", ".java", ".rb", ".sh", ".bash",
    ".yaml", ".yml", ".json", ".toml", ".conf", ".cfg",
    ".md", ".txt", ".log", ".xml", ".html",
}


def get_coordinator_url() -> str:
    """Load coordinator URL from profile. Avoids circular import with main.py."""
    try:
        import yaml
        profile_path = Path.home() / ".pk" / "profile.yaml"
        if profile_path.exists():
            with open(profile_path) as f:
                p = yaml.safe_load(f) or {}
                return p.get("coordinator_url", "https://localhost:30800")
    except Exception:
        pass
    return "https://localhost:30800"


def add_command(
    path: Optional[str] = typer.Argument(None, help="File or directory to add"),
    url: Optional[str] = typer.Option(None, "--url", help="URL to fetch and add"),
    cve: Optional[str] = typer.Option(None, "--cve", help="CVE ID to fetch from NVD"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
    json_output: bool = typer.Option(False, "--json"),
):
    """Add content to the paperknight AI knowledge base."""
    coordinator = get_coordinator_url()

    # CVE mode
    if cve is not None:
        cve_id = cve.upper().strip()
        if not quiet:
            console.print(f"[dim]Fetching {cve_id} from NVD...[/dim]")
        try:
            with httpx.Client(timeout=20.0, verify=False) as client:
                resp = client.post(f"{coordinator}/rag/add-cve", json={"cve_id": cve_id})
                if resp.status_code != 200:
                    err_console.print(f"[red]ERROR:[/red] {resp.json().get('detail', resp.text)}")
                    raise typer.Exit(1)
                data = resp.json()
            if json_output:
                import json; print(json.dumps(data))
            elif not quiet:
                console.print(
                    f"[green]✓[/green] Added {data['source']} "
                    f"(CVSS: {data['score']} {data['severity']})"
                )
            else:
                print(f"Added {data['source']}")
        except httpx.ConnectError:
            err_console.print(f"[red]Cannot reach coordinator at {coordinator}[/red]")
            raise typer.Exit(1)
        return

    # URL mode
    if url is not None:
        if not quiet:
            console.print(f"[dim]Fetching {url}...[/dim]")
        try:
            with httpx.Client(timeout=30.0, verify=False) as client:
                resp = client.post(f"{coordinator}/rag/add-url", json={"url": url})
                if resp.status_code != 200:
                    err_console.print(f"[red]ERROR:[/red] {resp.json().get('detail', resp.text)}")
                    raise typer.Exit(1)
                data = resp.json()
            if json_output:
                import json; print(json.dumps(data))
            elif not quiet:
                console.print(
                    f"[green]✓[/green] Added {data['source']} ({data['chunks']} chunks)"
                )
            else:
                print(f"Added {data['source']}")
        except httpx.ConnectError:
            err_console.print(f"[red]Cannot reach coordinator at {coordinator}[/red]")
            raise typer.Exit(1)
        return

    # File/directory mode
    if path is None:
        # Check stdin
        if not sys.stdin.isatty():
            content = sys.stdin.read()
            _add_content(coordinator, content, "stdin", "text", quiet, json_output)
            return
        err_console.print("[red]ERROR:[/red] Provide a path, --url, --cve, or pipe content")
        raise typer.Exit(1)

    target = Path(path)
    if not target.exists():
        err_console.print(f"[red]ERROR:[/red] Not found: {path}")
        raise typer.Exit(1)

    if target.is_file():
        _add_file(coordinator, target, quiet, json_output)
    elif target.is_dir():
        # Recursively add all supported files
        files = [
            f for f in target.rglob("*")
            if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
        ]
        if not files:
            err_console.print(f"[yellow]No supported files found in {path}[/yellow]")
            raise typer.Exit(1)
        if not quiet:
            console.print(f"[dim]Adding {len(files)} files from {path}...[/dim]")
        added = 0
        for f in files:
            try:
                _add_file(coordinator, f, quiet=True, json_output=False)
                added += 1
            except SystemExit:
                pass
        if not quiet:
            console.print(f"[green]✓[/green] Added {added}/{len(files)} files from {path}")
    else:
        err_console.print(f"[red]ERROR:[/red] Not a file or directory: {path}")
        raise typer.Exit(1)


def _add_file(coordinator: str, filepath: Path, quiet: bool, json_output: bool) -> None:
    """Add a single file to RAG."""
    if filepath.suffix.lower() not in SUPPORTED_EXTENSIONS:
        if not quiet:
            console.print(f"[yellow]Skipping[/yellow] {filepath} (unsupported type)")
        return

    try:
        content = filepath.read_text(errors="replace")
    except Exception as e:
        err_console.print(f"[red]Cannot read {filepath}:[/red] {e}")
        raise typer.Exit(1)

    if len(content.strip()) < 50:
        if not quiet:
            console.print(f"[yellow]Skipping[/yellow] {filepath} (too short)")
        return

    doc_type = "text" if filepath.suffix.lower() in {".md", ".txt", ".log"} else "code"
    _add_content(coordinator, content, str(filepath), doc_type, quiet, json_output)


def _add_content(
    coordinator: str,
    content: str,
    source: str,
    doc_type: str,
    quiet: bool,
    json_output: bool,
) -> None:
    """POST content to coordinator /rag/add."""
    try:
        with httpx.Client(timeout=30.0, verify=False) as client:
            resp = client.post(
                f"{coordinator}/rag/add",
                json={"content": content, "source": source, "doc_type": doc_type},
            )
            if resp.status_code != 200:
                err_console.print(f"[red]ERROR:[/red] {resp.json().get('detail', resp.text)}")
                raise typer.Exit(1)
            data = resp.json()

        if json_output:
            import json; print(json.dumps(data))
        elif not quiet:
            console.print(
                f"[green]✓[/green] Added {data['source']} ({data['chunks']} chunks)"
            )
        else:
            print(f"Added {data['source']}")

    except httpx.ConnectError:
        err_console.print(f"[red]Cannot reach coordinator at {coordinator}[/red]")
        raise typer.Exit(1)


def search_command(
    query: str = typer.Argument(..., help="Search query"),
    n_results: int = typer.Option(5, "--results", "-n", help="Number of results"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
    json_output: bool = typer.Option(False, "--json"),
):
    """Search the knowledge base without generating a response."""
    coordinator = get_coordinator_url()

    try:
        with httpx.Client(timeout=15.0, verify=False) as client:
            resp = client.get(
                f"{coordinator}/rag/search",
                params={"query": query, "n_results": n_results},
            )
            if resp.status_code != 200:
                err_console.print(f"[red]ERROR:[/red] {resp.json().get('detail', resp.text)}")
                raise typer.Exit(1)
            data = resp.json()

    except httpx.ConnectError:
        err_console.print(f"[red]Cannot reach coordinator at {coordinator}[/red]")
        raise typer.Exit(1)

    results = data.get("results", [])

    if json_output:
        import json; print(json.dumps(data, indent=2))
        return

    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return

    if quiet:
        for r in results:
            print(f"{r['source']}: {r['excerpt']}")
        return

    # Rich table output
    table = Table(title=f'Search: "{query}"', show_lines=True)
    table.add_column("Source", style="cyan", no_wrap=True, max_width=30)
    table.add_column("Type", style="dim", width=6)
    table.add_column("Match", style="dim", width=5)
    table.add_column("Excerpt")

    for r in results:
        # Lower distance = better match
        dist = r.get("distance", 1.0)
        match_pct = f"{max(0, int((1 - dist) * 100))}%"
        table.add_row(
            r.get("source", "?"),
            r.get("type", "?"),
            match_pct,
            r.get("excerpt", ""),
        )

    console.print(table)
