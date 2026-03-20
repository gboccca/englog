"""EngLog CLI — your engineering logbook from the terminal.

Usage:
    englog start <project> [-d description]   Start a session
    englog stop                               Stop the active session
    englog note <text>                        Add a note to active session
    englog summary [session_id]               Generate AI summary
    englog briefing <project>                 "Where did I leave off?"
    englog history [--project <name>]         List past sessions
    englog search <query>                     Search across all notes
    englog projects                           List all projects
    englog status                             Show current session status
    englog tray                               Run the system tray icon
"""

import sys
import os
import signal
import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown

from englog import database as db
from englog.session import (
    start_new_session,
    stop_current_session,
    add_session_note,
    get_active_session_info,
)
from englog.summary import generate_summary, generate_summary_stream, generate_briefing, check_ollama
from englog.capture import CaptureEngine
from englog.note_utils import detect_note_type

console = Console()

# Capture daemon — runs in background for the current CLI process
_capture_engine = None


@click.group()
def cli():
    """⚙ EngLog — Automatic engineering logbook."""
    db.init_db()


# ── start ─────────────────────────────────────────────────

@cli.command()
@click.argument("project")
@click.option("-d", "--description", default="", help="Brief project description")
@click.option("--no-capture", is_flag=True, help="Disable screenshot capture")
def start(project: str, description: str, no_capture: bool):
    """Start a new work session on a project."""
    result = start_new_session(project, description)

    if "error" in result:
        console.print(f"[red]✗[/red] {result['error']}")
        console.print("[dim]Tip: use 'englog resume' to restart capture, or 'englog stop' first.[/dim]")
        return

    session_id = result["session_id"]
    console.print(Panel(
        f"[bold green]Session started[/bold green]\n"
        f"Project: [cyan]{project}[/cyan]\n"
        f"Session ID: {session_id}\n\n"
        f"[dim]Add notes:[/dim]  englog note \"your note here\"\n"
        f"[dim]Stop:[/dim]       englog stop",
        title="⚙ EngLog",
        border_style="green",
    ))

    if not no_capture:
        # Start capture in background
        def on_capture(path, window, process):
            db.add_capture(session_id, path, window, process)

        global _capture_engine
        _capture_engine = CaptureEngine(session_id, on_capture=on_capture)
        _capture_engine.start()
        console.print(f"[dim]📸 Screenshot capture running (every 30s). Press Ctrl+C to stop.[/dim]")

        # Keep the process alive for capture
        def handle_signal(sig, frame):
            console.print("\n[yellow]Stopping capture... (session still active, stop with 'englog stop')[/yellow]")
            _capture_engine.stop()
            sys.exit(0)

        signal.signal(signal.SIGINT, handle_signal)
        if sys.platform == "win32":
            signal.signal(signal.SIGBREAK, handle_signal)

        # Block until interrupted — the capture runs in a daemon thread
        try:
            console.print("[dim]Capture running in background. This terminal is now the capture process.[/dim]")
            console.print("[dim]Open another terminal for 'englog note' and 'englog stop'.[/dim]")
            _capture_engine._thread.join()
        except (KeyboardInterrupt, SystemExit):
            _capture_engine.stop()


# ── stop ──────────────────────────────────────────────────

@cli.command()
@click.option("--summarize/--no-summarize", default=True, help="Auto-generate AI summary")
@click.option("--export/--no-export", default=True, help="Auto-export xlsx timesheet")
def stop(summarize: bool, export: bool):
    """Stop the active session."""
    result = stop_current_session()

    if "error" in result:
        console.print(f"[red]✗[/red] {result['error']}")
        return

    console.print(Panel(
        f"[bold yellow]Session stopped[/bold yellow]\n"
        f"Project: [cyan]{result['project']}[/cyan]\n"
        f"Duration: {result['started_at']} → {result['ended_at']}\n"
        f"Notes: {result['notes_count']} | Captures: {result['captures_count']}",
        title="⚙ EngLog",
        border_style="yellow",
    ))

    has_data = result["notes_count"] > 0 or result["captures_count"] > 0
    ollama_ok = check_ollama() if has_data else False

    if summarize and has_data:
        if not ollama_ok:
            from englog.config import OLLAMA_MODEL
            console.print(
                f"[red]✗ Ollama not available (looking for model '{OLLAMA_MODEL}').[/red]\n"
                f"  Check: [dim]ollama list[/dim]\n"
                f"  Pull model: [dim]ollama pull {OLLAMA_MODEL}[/dim]\n"
                f"  Retry later: [dim]englog summary {result['session_id']}[/dim]\n"
                f"  [dim]See 'FAQ — Failures and How to Fix Them' in the README.[/dim]"
            )
        else:
            console.print("\n[dim]Generating AI summary...[/dim]\n")
            text_parts = []
            with console.status("[bold cyan]Thinking...", spinner="dots"):
                stream = generate_summary_stream(result["session_id"])
                first_token = next(stream)
                text_parts.append(first_token)
            # First token received — stream the rest live
            console.print(first_token, end="")
            for token in stream:
                text_parts.append(token)
                console.print(token, end="", highlight=False)
            console.print()
            summary = "".join(text_parts)
            if summary.startswith("Error"):
                console.print(f"[red]✗ {summary}[/red]")
                console.print(f"[dim]Your notes and captures are safe. Retry: englog summary {result['session_id']}[/dim]")
            else:
                console.print()
                console.print(Panel(Markdown(summary), title="📋 Session Logbook", border_style="cyan"))

    if export and has_data:
        console.print("\n[dim]Generating timesheet...[/dim]")
        try:
            from englog.export import export_xlsx
            with console.status("[bold cyan]Building timesheet...", spinner="dots"):
                path = export_xlsx(result["session_id"], ollama_available=ollama_ok)
            console.print(f"[bold green]✓[/bold green] Timesheet exported: [link=file://{path}]{path}[/link]")
            if not ollama_ok:
                console.print("[yellow]Note: AI task classification skipped (Ollama not available). Time grid and notes are included.[/yellow]")
        except Exception as e:
            console.print(
                f"[red]✗ Export failed: {e}[/red]\n"
                f"  Your data is safe. Retry: [dim]englog export {result['session_id']}[/dim]\n"
                f"  [dim]See 'FAQ — Failures and How to Fix Them' in the README.[/dim]"
            )


# ── export ────────────────────────────────────────────────

@cli.command()
@click.argument("session_id", type=int, required=False)
@click.option("-o", "--output", default=None, help="Output file path")
def export(session_id: int, output: str):
    """Export a session as a formatted xlsx timesheet."""
    if not session_id:
        sessions = db.list_sessions(limit=1)
        if not sessions:
            console.print("[red]No sessions found.[/red]")
            return
        session_id = sessions[0]["id"]
        console.print(f"[dim]Using latest session #{session_id}[/dim]")

    ollama_ok = check_ollama()
    if not ollama_ok:
        console.print("[yellow]⚠ Ollama not available — exporting without AI task classification.[/yellow]")

    session = db.get_session(session_id)
    if not session:
        console.print(f"[red]Session {session_id} not found.[/red]")
        return

    console.print(f"[dim]Exporting session #{session_id} ({session['project_name']})...[/dim]")
    try:
        from englog.export import export_xlsx
        with console.status("[bold cyan]Generating timesheet...", spinner="dots"):
            path = export_xlsx(session_id, output_path=output, ollama_available=ollama_ok)
        console.print(f"\n[bold green]✓[/bold green] Timesheet exported: [link=file://{path}]{path}[/link]")
        console.print(f"[dim]Contains: Timesheet (30-min blocks) + Notes + AI Summary[/dim]")
    except Exception as e:
        console.print(
            f"[red]✗ Export failed: {e}[/red]\n"
            f"  Your data is safe. Retry: [dim]englog export {session_id}[/dim]\n"
            f"  [dim]See 'FAQ — Failures and How to Fix Them' in the README.[/dim]"
        )


# ── resume ─────────────────────────────────────────────────

@cli.command()
def resume():
    """Resume screen capture on an active session (after terminal was closed)."""
    active = get_active_session_info()
    if not active:
        console.print("[dim]○ No active session to resume.[/dim]")
        # Check if there's an orphaned session in DB
        session = db.get_active_session()
        if session:
            console.print(
                f"[yellow]Found orphaned session #{session['id']} on "
                f"[cyan]{session['project_name']}[/cyan] "
                f"(started {session['started_at']}).[/yellow]"
            )
            if click.confirm("Resume this session?", default=True):
                from englog.session import _save_active_session
                _save_active_session(session["id"], session["project_name"])
                active = {"session_id": session["id"], "project": session["project_name"]}
            else:
                if click.confirm("Stop it instead?", default=False):
                    db.stop_session(session["id"])
                    console.print("[yellow]Session stopped.[/yellow]")
                return
        else:
            console.print("[dim]Start a new session with: englog start <project>[/dim]")
            return

    session_id = active["session_id"]
    notes = db.get_session_notes(session_id)
    captures = db.get_session_captures(session_id)

    console.print(Panel(
        f"[bold green]Resuming capture[/bold green]\n"
        f"Project: [cyan]{active['project']}[/cyan]\n"
        f"Session: #{session_id}\n"
        f"Notes so far: {len(notes)} | Captures so far: {len(captures)}\n\n"
        f"[dim]Add notes:[/dim]  englog note \"your note here\"\n"
        f"[dim]Stop:[/dim]       englog stop",
        title="⚙ EngLog",
        border_style="green",
    ))

    # Restart the capture daemon
    def on_capture(path, window, process):
        db.add_capture(session_id, path, window, process)

    global _capture_engine
    _capture_engine = CaptureEngine(session_id, on_capture=on_capture)
    _capture_engine.start()
    console.print(f"[dim]📸 Screenshot capture resumed. Press Ctrl+C to stop capture (session stays active).[/dim]")

    def handle_signal(sig, frame):
        console.print("\n[yellow]Stopping capture... (session still active)[/yellow]")
        _capture_engine.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    if sys.platform == "win32":
        signal.signal(signal.SIGBREAK, handle_signal)

    try:
        _capture_engine._thread.join()
    except (KeyboardInterrupt, SystemExit):
        _capture_engine.stop()


# ── note ──────────────────────────────────────────────────

@cli.command()
@click.argument("text", nargs=-1, required=True)
@click.option("-t", "--type", "note_type", default="auto",
              type=click.Choice(["auto", "decision", "observation", "blocker"]),
              help="Note type (auto-detected by default)")
def note(text: tuple, note_type: str):
    """Add a note to the active session."""
    content = " ".join(text)

    # Auto-detect note type from content
    if note_type == "auto":
        note_type = detect_note_type(content)

    result = add_session_note(content, note_type)

    if "error" in result:
        console.print(f"[red]✗[/red] {result['error']}")
        return

    type_colors = {"decision": "bold magenta", "blocker": "bold red", "observation": "bold blue"}
    type_icons = {"decision": "⚡", "blocker": "🚫", "observation": "📝"}
    color = type_colors.get(note_type, "white")
    icon = type_icons.get(note_type, "•")

    console.print(f"  {icon} [{color}][{note_type.upper()}][/{color}] {content}")


# ── summary ───────────────────────────────────────────────

@cli.command()
@click.argument("session_id", type=int, required=False)
def summary(session_id: int):
    """Generate an AI summary for a session."""
    if not session_id:
        sessions = db.list_sessions(limit=1)
        if not sessions:
            console.print("[red]No sessions found.[/red]")
            return
        session_id = sessions[0]["id"]
        console.print(f"[dim]Using latest session #{session_id}[/dim]")

    # Check if summary already exists
    session = db.get_session(session_id)
    if not session:
        console.print(f"[red]Session {session_id} not found.[/red]")
        return

    if session.get("summary"):
        console.print(Panel(Markdown(session["summary"]), title="📋 Session Logbook (cached)", border_style="cyan"))
        if not click.confirm("Regenerate?", default=False):
            return

    if not check_ollama():
        from englog.config import OLLAMA_MODEL
        console.print(
            f"[red]✗ Ollama not available (looking for model '{OLLAMA_MODEL}').[/red]\n"
            f"  Check: [dim]ollama list[/dim]  |  Pull model: [dim]ollama pull {OLLAMA_MODEL}[/dim]\n"
            f"  Install: [dim]https://ollama.com[/dim]\n"
            f"  [dim]See 'FAQ — Failures and How to Fix Them' in the README.[/dim]"
        )
        return

    console.print("[dim]Generating summary...[/dim]\n")
    text_parts = []
    with console.status("[bold cyan]Waiting for Ollama...", spinner="dots"):
        stream = generate_summary_stream(session_id)
        first_token = next(stream)
        text_parts.append(first_token)
    # First token received — now stream the rest live
    console.print(first_token, end="")
    for token in stream:
        text_parts.append(token)
        console.print(token, end="", highlight=False)
    console.print()  # final newline
    text = "".join(text_parts)
    if not text.startswith("Error"):
        console.print()
        console.print(Panel(Markdown(text), title="📋 Session Logbook", border_style="cyan"))


# ── briefing ──────────────────────────────────────────────

@cli.command()
@click.argument("project")
def briefing(project: str):
    """Get a 'where did I leave off?' briefing for a project."""
    if not check_ollama():
        from englog.config import OLLAMA_MODEL
        console.print(
            f"[red]✗ Ollama not available (looking for model '{OLLAMA_MODEL}').[/red]\n"
            f"  Check: [dim]ollama list[/dim]  |  Pull model: [dim]ollama pull {OLLAMA_MODEL}[/dim]\n"
            f"  [dim]See 'FAQ — Failures and How to Fix Them' in the README.[/dim]"
        )
        return

    with console.status(f"[bold cyan]Preparing briefing for {project}...", spinner="dots"):
        text = generate_briefing(project)
    console.print(Panel(Markdown(text), title=f"📍 Briefing — {project}", border_style="green"))


# ── status ────────────────────────────────────────────────

@cli.command()
def status():
    """Show current session status."""
    active = get_active_session_info()
    if active:
        session = db.get_session(active["session_id"])
        notes = db.get_session_notes(active["session_id"])
        captures = db.get_session_captures(active["session_id"])
        console.print(Panel(
            f"[bold green]● Active[/bold green]\n"
            f"Project: [cyan]{active['project']}[/cyan]\n"
            f"Session: #{active['session_id']}\n"
            f"Started: {session['started_at']}\n"
            f"Notes: {len(notes)} | Captures: {len(captures)}",
            title="⚙ EngLog Status",
            border_style="green",
        ))
        if notes:
            console.print("\n[bold]Recent notes:[/bold]")
            for n in notes[-5:]:
                console.print(f"  [{n['timestamp']}] ({n['note_type']}) {n['content']}")
    else:
        console.print("[dim]○ No active session. Start one with: englog start <project>[/dim]")


# ── history ───────────────────────────────────────────────

@cli.command()
@click.option("-p", "--project", default=None, help="Filter by project name")
@click.option("-n", "--limit", default=15, help="Number of sessions to show")
def history(project: str, limit: int):
    """List past sessions."""
    sessions = db.list_sessions(project_name=project, limit=limit)
    if not sessions:
        console.print("[dim]No sessions found.[/dim]")
        return

    table = Table(title="Session History", show_lines=True)
    table.add_column("ID", style="dim", width=5)
    table.add_column("Project", style="cyan")
    table.add_column("Started", style="green")
    table.add_column("Ended")
    table.add_column("Notes", justify="right")
    table.add_column("Summary", width=40)

    for s in sessions:
        notes_count = len(db.get_session_notes(s["id"]))
        summary_preview = (s.get("summary") or "—")[:60]
        if s.get("summary") and len(s["summary"]) > 60:
            summary_preview += "..."
        table.add_row(
            str(s["id"]),
            s["project_name"],
            s["started_at"],
            s.get("ended_at") or "[green]active[/green]",
            str(notes_count),
            summary_preview,
        )

    console.print(table)


# ── search ────────────────────────────────────────────────

@cli.command()
@click.argument("query")
@click.option("-p", "--project", default=None, help="Limit to a project")
def search(query: str, project: str):
    """Search across all notes."""
    results = db.search_notes(query, project_name=project)
    if not results:
        console.print(f"[dim]No notes matching '{query}'.[/dim]")
        return

    console.print(f"[bold]Found {len(results)} note(s) matching '{query}':[/bold]\n")
    for r in results:
        console.print(
            f"  [{r['timestamp']}] [cyan]{r['project_name']}[/cyan] "
            f"({r['note_type']}) {r['content']}"
        )


# ── projects ──────────────────────────────────────────────

@cli.command()
def projects():
    """List all projects."""
    projs = db.list_projects()
    if not projs:
        console.print("[dim]No projects yet. Start one with: englog start <project-name>[/dim]")
        return

    table = Table(title="Projects")
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("Created", style="dim")
    table.add_column("Sessions", justify="right")

    for p in projs:
        session_count = len(db.list_sessions(project_name=p["name"], limit=100))
        table.add_row(p["name"], p["description"] or "—", p["created_at"], str(session_count))

    console.print(table)


# ── management ───────────────────────────────────────────

@cli.command("rename-project")
@click.argument("old_name")
@click.argument("new_name")
def rename_project(old_name: str, new_name: str):
    """Rename a project."""
    project = db.get_project(old_name)
    if not project:
        console.print(f"[red]Project '{old_name}' not found.[/red]")
        return

    result = db.rename_project(project["id"], new_name)
    if "error" in result:
        console.print(f"[red]{result['error']}[/red]")
        return

    # Update pidfile if this project has an active session
    active = get_active_session_info()
    if active and active.get("project") == old_name:
        from englog.session import _save_active_session
        _save_active_session(active["session_id"], new_name)

    console.print(f"[bold green]Renamed[/bold green] [cyan]{old_name}[/cyan] → [cyan]{new_name}[/cyan]")


@cli.command("delete-project")
@click.argument("name")
@click.option("--force", is_flag=True, help="Skip confirmation prompt")
def delete_project(name: str, force: bool):
    """Delete a project and all its sessions, notes, captures, and screenshots."""
    project = db.get_project(name)
    if not project:
        console.print(f"[red]Project '{name}' not found.[/red]")
        return

    sessions = db.list_sessions(project_name=name, limit=1000)
    total_notes = sum(len(db.get_session_notes(s["id"])) for s in sessions)
    total_captures = sum(len(db.get_session_captures(s["id"])) for s in sessions)

    if not force:
        console.print(
            f"[bold yellow]This will permanently delete:[/bold yellow]\n"
            f"  Project: [cyan]{name}[/cyan]\n"
            f"  {len(sessions)} session(s), {total_notes} note(s), {total_captures} capture(s) + screenshots"
        )
        if not click.confirm("Continue?", default=False):
            console.print("[dim]Cancelled.[/dim]")
            return

    result = db.delete_project(project["id"])
    if "error" in result:
        console.print(f"[red]{result['error']}[/red]")
        return

    console.print(
        f"[bold green]Deleted[/bold green] project [cyan]{name}[/cyan] "
        f"({result['deleted_sessions']} sessions, {result['deleted_notes']} notes, {result['deleted_captures']} captures)"
    )


@cli.command("delete-session")
@click.argument("session_id", type=int)
@click.option("--force", is_flag=True, help="Skip confirmation prompt")
def delete_session(session_id: int, force: bool):
    """Delete a session and all its notes, captures, and screenshots."""
    session = db.get_session(session_id)
    if not session:
        console.print(f"[red]Session {session_id} not found.[/red]")
        return

    notes = db.get_session_notes(session_id)
    captures = db.get_session_captures(session_id)

    if not force:
        console.print(
            f"[bold yellow]This will permanently delete:[/bold yellow]\n"
            f"  Session #{session_id} on [cyan]{session['project_name']}[/cyan] ({session['started_at'][:10]})\n"
            f"  {len(notes)} note(s), {len(captures)} capture(s) + screenshots"
        )
        if not click.confirm("Continue?", default=False):
            console.print("[dim]Cancelled.[/dim]")
            return

    result = db.delete_session(session_id)
    if "error" in result:
        console.print(f"[red]{result['error']}[/red]")
        return

    console.print(
        f"[bold green]Deleted[/bold green] session #{session_id} "
        f"({result['deleted_notes']} notes, {result['deleted_captures']} captures)"
    )


# ── demo ─────────────────────────────────────────────────

@cli.command()
def demo():
    """Populate the database with a realistic fictitious project for testing.

    Creates a project 'SolarSailNav' with one completed session containing
    realistic engineering notes and capture metadata, ready for summary
    generation and xlsx export.
    """
    project_name = "SolarSailNav"

    # Check if demo project already exists
    existing = db.get_project(project_name)
    if existing:
        console.print(f"[yellow]Demo project '{project_name}' already exists.[/yellow]")
        console.print("[dim]Delete it first with: englog delete-project SolarSailNav[/dim]")
        return

    # Create project with rich context
    project_id = db.create_project(project_name, "Solar sail navigation GNC subsystem for 0.1 AU heliocentric mission")
    db.update_project_context(project_name, (
        "SolarSailNav is the GNC (Guidance, Navigation & Control) subsystem for a solar sail "
        "spacecraft targeting a 0.1 AU heliocentric orbit. The sail is 40m x 40m aluminised Kapton. "
        "Key challenges: attitude control without reaction wheels (sail cant angles only), navigation "
        "with degraded star tracker performance near the Sun, and thermal protection of the bus. "
        "The team uses MATLAB/Simulink for dynamics, STK for orbit visualisation, and a custom "
        "Python toolchain for Monte Carlo dispersion analysis. Current phase: preliminary design review (PDR)."
    ))
    db.update_project_rules(project_name, (
        "- Always mention specific file names and tools when visible in window titles\n"
        "- Distinguish between simulation work (MATLAB/Python) and documentation (Word/PowerPoint)\n"
        "- Flag any thermal constraint violations as blockers\n"
        "- Use SI units throughout"
    ))

    # Create a completed session with explicit timestamps
    conn = db.get_connection()

    session_date = "2026-03-18"
    session_start = f"{session_date} 08:45:00"
    session_end = f"{session_date} 17:12:00"

    cur = conn.execute(
        "INSERT INTO sessions (project_id, started_at, ended_at, is_active) VALUES (?, ?, ?, 0)",
        (project_id, session_start, session_end),
    )
    sid = cur.lastrowid

    # ── Notes: a realistic day of engineering work ──
    notes = [
        ("08:47:00", "observation", "Starting day with review of Monte Carlo results from overnight batch run — 10,000 trajectories completed"),
        ("08:58:00", "observation", "3-sigma dispersion on perihelion distance is +/- 0.008 AU, within the 0.01 AU requirement margin"),
        ("09:15:00", "decision", "Decided to keep the 2-axis sun sensor as primary attitude reference below 0.3 AU — star tracker FOV exclusion zone is too large near the Sun"),
        ("09:32:00", "observation", "Reviewing sail cant angle authority — max 35 deg gives sufficient torque for detumble from worst-case separation attitude"),
        ("09:51:00", "blocker", "Waiting on updated thermal model from Marie — need to verify bus temperature stays below 85C at 0.1 AU before we can finalise the electronics layout"),
        ("10:20:00", "decision", "Switching from fixed-gain to LQR controller for the approach phase because the dynamics change too fast below 0.2 AU for a single gain set to work"),
        ("10:45:00", "observation", "LQR weight tuning in Simulink — penalising sail angle rate 10x more than position error gives smoother trajectories"),
        ("11:10:00", "decision", "Going with 4 reflectance modulation panels instead of 2 — redundancy analysis shows single-panel failure would leave us uncontrollable with only 2"),
        ("11:35:00", "observation", "Updated the mass budget spreadsheet — 4-panel config adds 0.8 kg, total GNC mass now 12.3 kg (allocation is 14 kg, 12% margin)"),
        ("12:00:00", "observation", "Lunch break — left the 5000-case Monte Carlo batch running on the cluster"),
        ("13:15:00", "observation", "Back from lunch. Batch still running, 3200/5000 cases done. Reviewing the PDR slide deck meanwhile"),
        ("13:42:00", "blocker", "STK license server is down — can't generate the orbit visualisation figures for the PDR slides. Emailed IT support"),
        ("14:05:00", "observation", "Working on the navigation error budget in Excel while waiting for STK. Star tracker noise model updated with latest datasheet values from Sodern"),
        ("14:30:00", "decision", "Decided to add a second sun sensor on the -X face because single-sensor coverage drops below 95% during the spiral-in phase due to sail shadowing"),
        ("14:55:00", "observation", "Monte Carlo batch completed. Post-processing results — generating CDF plots for perihelion distance and sail temperature"),
        ("15:20:00", "decision", "Chose to baseline the 45-day transfer instead of 38-day because it reduces peak sail temperature from 310C to 275C, well within Kapton's 400C limit"),
        ("15:48:00", "observation", "STK back online. Generated 3D orbit animation and perihelion passage plot for PDR slides"),
        ("16:10:00", "observation", "Updated the navigation filter design doc — added section on sun sensor measurement model and noise characteristics"),
        ("16:35:00", "blocker", "Need Pierre to review the filter covariance tuning before PDR — the Q matrix values are educated guesses and could use a second opinion"),
        ("16:55:00", "observation", "Committed all updated Simulink models and Python scripts to the shared repo. Tagged as pre-PDR-v2"),
    ]

    for ts, ntype, content in notes:
        conn.execute(
            "INSERT INTO notes (session_id, timestamp, content, note_type) VALUES (?, ?, ?, ?)",
            (sid, f"{session_date} {ts}", content, ntype),
        )

    # ── Captures: realistic window/process transitions ──
    captures = [
        ("08:45:30", "MonteCarlo_results_v4.xlsx - Excel", "EXCEL.EXE"),
        ("08:52:00", "MonteCarlo_results_v4.xlsx - Excel", "EXCEL.EXE"),
        ("09:00:00", "sail_attitude_sim.slx - Simulink", "MATLAB.exe"),
        ("09:10:00", "sail_attitude_sim.slx - Simulink", "MATLAB.exe"),
        ("09:20:00", "sun_sensor_spec_Sodern.pdf - Adobe Acrobat", "Acrobat.exe"),
        ("09:35:00", "sail_attitude_sim.slx - Simulink", "MATLAB.exe"),
        ("09:50:00", "Outlook - Marie thermal model", "OUTLOOK.EXE"),
        ("10:00:00", "sail_approach_LQR.slx - Simulink", "MATLAB.exe"),
        ("10:15:00", "sail_approach_LQR.slx - Simulink", "MATLAB.exe"),
        ("10:30:00", "sail_approach_LQR.slx - Simulink", "MATLAB.exe"),
        ("10:50:00", "sail_approach_LQR.slx - Simulink", "MATLAB.exe"),
        ("11:05:00", "redundancy_analysis.py - VSCode", "Code.exe"),
        ("11:20:00", "redundancy_analysis.py - VSCode", "Code.exe"),
        ("11:40:00", "GNC_mass_budget_v3.xlsx - Excel", "EXCEL.EXE"),
        ("13:15:00", "PDR_GNC_slides_v2.pptx - PowerPoint", "POWERPNT.EXE"),
        ("13:30:00", "PDR_GNC_slides_v2.pptx - PowerPoint", "POWERPNT.EXE"),
        ("13:45:00", "PDR_GNC_slides_v2.pptx - PowerPoint", "POWERPNT.EXE"),
        ("14:00:00", "Outlook - IT Support RE: STK license", "OUTLOOK.EXE"),
        ("14:10:00", "nav_error_budget_v2.xlsx - Excel", "EXCEL.EXE"),
        ("14:25:00", "nav_error_budget_v2.xlsx - Excel", "EXCEL.EXE"),
        ("14:40:00", "sun_sensor_coverage.py - VSCode", "Code.exe"),
        ("14:55:00", "mc_postprocess.py - VSCode", "Code.exe"),
        ("15:10:00", "mc_postprocess.py - VSCode", "Code.exe"),
        ("15:25:00", "transfer_trade.py - VSCode", "Code.exe"),
        ("15:50:00", "STK 12 - SolarSail_mission", "STKMain.exe"),
        ("16:05:00", "STK 12 - SolarSail_mission", "STKMain.exe"),
        ("16:15:00", "nav_filter_design_v3.docx - Word", "WINWORD.EXE"),
        ("16:35:00", "nav_filter_design_v3.docx - Word", "WINWORD.EXE"),
        ("16:50:00", "Git Bash - ~/SolarSailNav", "git-bash.exe"),
        ("17:00:00", "PDR_GNC_slides_v2.pptx - PowerPoint", "POWERPNT.EXE"),
    ]

    for ts, window, process in captures:
        conn.execute(
            "INSERT INTO captures (session_id, timestamp, screenshot_path, active_window, active_process) VALUES (?, ?, NULL, ?, ?)",
            (sid, f"{session_date} {ts}", window, process),
        )

    conn.commit()
    conn.close()

    console.print(Panel(
        f"[bold green]Demo data created[/bold green]\n\n"
        f"Project: [cyan]{project_name}[/cyan]\n"
        f"  Solar sail GNC subsystem — realistic aerospace engineering session\n\n"
        f"Session: [cyan]#{sid}[/cyan] ({session_date}, 08:45-17:12)\n"
        f"  {len(notes)} notes (decisions, blockers, observations)\n"
        f"  {len(captures)} screen captures (MATLAB, Excel, VSCode, STK, ...)\n\n"
        f"[bold]Try these now:[/bold]\n"
        f"  [dim]englog summary {sid}[/dim]        Generate AI logbook entry\n"
        f"  [dim]englog export {sid}[/dim]         Generate xlsx timesheet\n"
        f"  [dim]englog history -p {project_name}[/dim]  View session in history\n"
        f"  [dim]englog search \"sail\"[/dim]         Search across notes\n\n"
        f"Or open [cyan]englog-gui[/cyan] and explore the Summary / History / Project tabs.\n\n"
        f"[dim]To remove: englog delete-project {project_name}[/dim]",
        title="Demo Data",
        border_style="green",
    ))


# ── tray ──────────────────────────────────────────────────

@cli.command()
def tray():
    """Run the system tray icon (background mode)."""
    from englog.tray import TrayApp
    console.print("[dim]Starting EngLog tray icon...[/dim]")
    app = TrayApp()
    app.run()


# ── Entry point ───────────────────────────────────────────

def main():
    cli()


if __name__ == "__main__":
    main()
