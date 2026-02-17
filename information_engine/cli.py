"""Typer CLI for the Information Engine."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from .config import load_config
from .database import get_db, init_db

app = typer.Typer(name="info-engine", help="On-demand business intelligence research tool")
console = Console()


def _get_db_and_config(config_path: str | None = None):
    """Load config and database connection."""
    config = load_config(config_path)
    db = get_db(config.database_path)
    init_db(db)
    return db, config


# --- RESEARCH ---

@app.command()
def research(
    topic: str = typer.Argument(..., help="Topic to research"),
    deep: bool = typer.Option(False, "--deep", "-d", help="Deep mode: Research API + follow-up searches + extract"),
    config_path: str = typer.Option(None, "--config", "-c", help="Path to config.yaml"),
):
    """Research a topic and create a knowledge playbook."""
    db, config = _get_db_and_config(config_path)

    if not config.api_keys.tavily:
        console.print("[red]TAVILY_API_KEY not set.[/red] Add it to your .env file.")
        raise typer.Exit(1)
    if not config.api_keys.anthropic:
        console.print("[red]ANTHROPIC_API_KEY not set.[/red] Add it to your .env file.")
        raise typer.Exit(1)

    from .researcher import run_research

    mode = "deep" if deep else "standard"
    console.print(f"\n[bold cyan]Researching:[/bold cyan] {topic}")
    console.print(f"[dim]Mode: {mode} | Tavily: {config.research.tavily_model}[/dim]\n")

    try:
        result = run_research(db, config, topic, deep=deep)
    except Exception as e:
        console.print(f"\n[red]Research failed:[/red] {e}")
        raise typer.Exit(1)

    # Display result
    console.print(f"\n[bold green]Playbook created![/bold green]")
    console.print(f"  ID: #{result['playbook_id']}")
    console.print(f"  Title: {result['title']}")
    console.print(f"  Domain: {result['domain']}")
    console.print(f"  Relevance: {result['relevance_score']:.0%}")
    console.print(f"  Insights: {result['insights_count']} | Actions: {result['action_items_count']}")
    console.print(f"  Sources: {result['sources_count']}")
    console.print(f"  Cost: ${result['cost_usd']:.4f}")
    console.print(f"\n  [dim]View full playbook: info-engine view {result['playbook_id']}[/dim]")


# --- BROWSE ---

@app.command()
def browse(
    domain: str = typer.Option(None, "--domain", "-d", help="Filter by domain"),
    search: str = typer.Option(None, "--search", "-s", help="Full-text search"),
    limit: int = typer.Option(20, "--limit", "-l", help="Max results"),
    config_path: str = typer.Option(None, "--config", "-c"),
):
    """Browse the knowledge base."""
    db, config = _get_db_and_config(config_path)
    from .database import list_playbooks, search_playbooks

    if search:
        playbooks = search_playbooks(db, search, limit=limit)
        console.print(f"\n[bold]Search results for '{search}':[/bold]\n")
    else:
        playbooks = list_playbooks(db, domain=domain, limit=limit)
        title = f"Knowledge Base — {domain}" if domain else "Knowledge Base"
        console.print(f"\n[bold]{title}[/bold]\n")

    if not playbooks:
        console.print("[yellow]No playbooks found.[/yellow]")
        console.print("[dim]Run 'info-engine research \"your topic\"' to start building knowledge.[/dim]")
        return

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("ID", style="bold", width=4)
    table.add_column("Title", min_width=30)
    table.add_column("Domain", width=12)
    table.add_column("Rel.", width=5, justify="right")
    table.add_column("Mode", width=8)
    table.add_column("Date", width=10)

    for pb in playbooks:
        rel_color = "green" if pb["relevance_score"] >= 0.7 else "yellow" if pb["relevance_score"] >= 0.5 else "dim"
        table.add_row(
            str(pb["id"]),
            pb["title"][:50],
            pb["domain"],
            f"[{rel_color}]{pb['relevance_score']:.0%}[/{rel_color}]",
            pb.get("mode", "std"),
            pb["created_at"][:10] if pb.get("created_at") else "",
        )

    console.print(table)
    console.print(f"\n[dim]{len(playbooks)} playbook(s) shown.[/dim]")


# --- VIEW ---

@app.command()
def view(
    playbook_id: int = typer.Argument(..., help="Playbook ID to view"),
    config_path: str = typer.Option(None, "--config", "-c"),
):
    """View a full playbook."""
    db, config = _get_db_and_config(config_path)
    from .database import get_playbook

    pb = get_playbook(db, playbook_id)
    if not pb:
        console.print(f"[red]Playbook #{playbook_id} not found.[/red]")
        raise typer.Exit(1)

    # Header
    console.print(f"\n[bold cyan]#{pb['id']} — {pb['title']}[/bold cyan]")
    console.print(f"[dim]Domain: {pb['domain']} | Relevance: {pb['relevance_score']:.0%} | Mode: {pb.get('mode', 'standard')} | {pb['created_at'][:10]}[/dim]")
    console.print(f"[dim]Topic: {pb['topic']}[/dim]\n")

    # Summary
    console.print(Panel(pb["summary"], title="Summary", border_style="cyan"))

    # Key Insights
    insights = pb.get("key_insights", [])
    if insights:
        console.print("\n[bold]Key Insights[/bold]")
        for i, insight in enumerate(insights, 1):
            console.print(f"  {i}. {insight}")

    # Action Items
    actions = pb.get("action_items", [])
    if actions:
        console.print("\n[bold]Action Items[/bold]")
        for action in actions:
            console.print(f"  [ ] {action}")

    # Sources
    sources = pb.get("sources", [])
    if sources:
        console.print("\n[bold]Sources[/bold]")
        for s in sources:
            if isinstance(s, dict):
                title = s.get("title", s.get("url", ""))
                url = s.get("url", "")
                console.print(f"  [dim]- {title}[/dim]")
                if url and url != title:
                    console.print(f"    [dim]{url}[/dim]")
            else:
                console.print(f"  [dim]- {s}[/dim]")

    console.print()


# --- ASK ---

@app.command()
def ask(
    question: str = typer.Argument(..., help="Question to answer from your knowledge base"),
    limit: int = typer.Option(10, "--limit", "-l", help="Max playbooks to use as context"),
    config_path: str = typer.Option(None, "--config", "-c"),
):
    """Ask a question against your existing knowledge base."""
    db, config = _get_db_and_config(config_path)

    if not config.api_keys.anthropic:
        console.print("[red]ANTHROPIC_API_KEY not set.[/red] Add it to your .env file.")
        raise typer.Exit(1)

    from .database import search_playbooks, list_playbooks
    from .synthesizer import ask_knowledge_base

    # Find relevant playbooks
    relevant = search_playbooks(db, question, limit=limit)
    if not relevant:
        # Fall back to most recent playbooks
        relevant = list_playbooks(db, limit=limit)

    if not relevant:
        console.print("[yellow]No playbooks in knowledge base yet.[/yellow]")
        console.print("[dim]Run 'info-engine research \"topic\"' to build your knowledge base first.[/dim]")
        return

    # Build context from playbooks
    context_parts = []
    for pb in relevant:
        insights = pb.get("key_insights", [])
        actions = pb.get("action_items", [])
        insights_text = "\n".join(f"  - {i}" for i in insights) if insights else ""
        actions_text = "\n".join(f"  - {a}" for a in actions) if actions else ""
        context_parts.append(
            f"### Playbook #{pb['id']}: {pb['title']} (domain: {pb['domain']}, relevance: {pb['relevance_score']:.0%})\n"
            f"{pb['summary']}\n"
            f"Key insights:\n{insights_text}\n"
            f"Action items:\n{actions_text}"
        )

    knowledge_context = "\n\n---\n\n".join(context_parts)

    console.print(f"\n[bold cyan]Asking:[/bold cyan] {question}")
    console.print(f"[dim]Using {len(relevant)} playbook(s) as context[/dim]\n")

    try:
        response, cost = ask_knowledge_base(db, config, question, knowledge_context)
    except Exception as e:
        console.print(f"\n[red]Ask failed:[/red] {e}")
        raise typer.Exit(1)

    # Display answer
    console.print(Panel(response.answer, title="Answer", border_style="green"))
    console.print(f"[dim]Confidence: {response.confidence:.0%} | Cost: ${cost:.4f}[/dim]")

    if response.related_playbook_ids:
        console.print(f"[dim]Based on playbooks: {', '.join(f'#{i}' for i in response.related_playbook_ids)}[/dim]")

    if response.knowledge_gaps:
        console.print("\n[bold yellow]Knowledge gaps — consider researching:[/bold yellow]")
        for gap in response.knowledge_gaps:
            console.print(f"  - {gap}")

    console.print()


# --- SYNC ---

@app.command()
def sync(
    config_path: str = typer.Option(None, "--config", "-c"),
):
    """Sync playbooks to Notion Knowledge Base."""
    db, config = _get_db_and_config(config_path)

    if not config.api_keys.notion:
        console.print("[red]NOTION_API_KEY not set.[/red] Add it to your .env file.")
        raise typer.Exit(1)

    from .sync.notion_sync import NotionSync

    console.print("[bold cyan]Syncing to Notion...[/bold cyan]")
    notion_sync = NotionSync(db, config)

    try:
        result = notion_sync.sync_playbooks()
    except Exception as e:
        console.print(f"\n[red]Sync failed:[/red] {e}")
        raise typer.Exit(1)

    console.print(f"\n[bold]Results:[/bold]")
    console.print(f"  Synced: {result['synced']}")
    console.print(f"  Skipped: {result['skipped']}")

    if result["synced"] == 0 and result["skipped"] == 0:
        console.print("[dim]  No new playbooks to sync.[/dim]")


# --- STATUS ---

@app.command()
def status(
    config_path: str = typer.Option(None, "--config", "-c"),
):
    """Show knowledge base overview."""
    db, config = _get_db_and_config(config_path)
    from .database import get_playbook_count
    from .cost_tracker import get_daily_cost, get_monthly_cost

    counts = get_playbook_count(db)

    table = Table(title="Information Engine Status", show_header=True, header_style="bold cyan")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    table.add_row("Total playbooks", str(counts["total"]))
    table.add_row("", "")

    for domain, count in counts["by_domain"].items():
        table.add_row(f"  {domain}", str(count))

    # Research sessions
    total_sessions = db.execute("SELECT COUNT(*) FROM research_sessions").fetchone()[0]
    completed = db.execute("SELECT COUNT(*) FROM research_sessions WHERE status = 'completed'").fetchone()[0]
    failed = db.execute("SELECT COUNT(*) FROM research_sessions WHERE status = 'failed'").fetchone()[0]

    table.add_row("", "")
    table.add_row("Research sessions", str(total_sessions))
    table.add_row("  Completed", f"[green]{completed}[/green]")
    if failed:
        table.add_row("  Failed", f"[red]{failed}[/red]")

    # Notion sync
    synced = db.execute("SELECT COUNT(*) FROM notion_sync WHERE sync_status = 'synced'").fetchone()[0]
    table.add_row("", "")
    table.add_row("Synced to Notion", str(synced))

    # Costs
    table.add_row("", "")
    table.add_row("Cost today", f"${get_daily_cost(db):.4f}")
    table.add_row("Cost this month", f"${get_monthly_cost(db):.4f}")

    console.print(table)


# --- COSTS ---

@app.command()
def costs(
    days: int = typer.Option(7, "--days", "-d", help="Number of days to report"),
    config_path: str = typer.Option(None, "--config", "-c"),
):
    """Show API cost breakdown."""
    db, config = _get_db_and_config(config_path)
    from .cost_tracker import get_cost_breakdown, get_daily_cost, get_monthly_cost

    table = Table(title=f"API Costs (Last {days} Days)", show_header=True, header_style="bold cyan")
    table.add_column("Operation")
    table.add_column("Model")
    table.add_column("Calls", justify="right")
    table.add_column("Input Tokens", justify="right")
    table.add_column("Output Tokens", justify="right")
    table.add_column("Cost (USD)", justify="right", style="green")

    breakdown = get_cost_breakdown(db, days)
    for item in breakdown:
        model_short = item["model"].split("-")[1] if "-" in item["model"] else item["model"]
        table.add_row(
            item["operation"],
            model_short,
            str(item["calls"]),
            f"{item['total_input_tokens']:,}",
            f"{item['total_output_tokens']:,}",
            f"${item['total_cost']:.4f}",
        )

    console.print(table)
    console.print(f"\nToday: ${get_daily_cost(db):.4f}")
    console.print(f"This month: ${get_monthly_cost(db):.4f}")


# --- INIT ---

@app.command(name="init")
def init_database(
    config_path: str = typer.Option(None, "--config", "-c"),
):
    """Initialize the database."""
    db, config = _get_db_and_config(config_path)
    console.print(f"[green]Database initialized at {config.database_path}[/green]")


if __name__ == "__main__":
    app()
