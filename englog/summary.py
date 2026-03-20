"""AI-powered session summary generation via Ollama."""

import json
import requests
from datetime import datetime
from typing import Optional

from englog.config import OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_NUM_CTX, MAX_CONTEXT_CHARS, OLLAMA_TIMEOUT
from englog import database as db


SYSTEM_PROMPT = """You are EngLog, an engineering logbook assistant. Your job is to transform 
raw session data (timestamped notes and activity metadata) into a clean, structured logbook entry.

Rules:
- Write in past tense, professional but concise
- Group related activities into logical blocks
- Highlight DECISIONS clearly — these are the most valuable part of the logbook
- Note what the engineer was working on (from window/process data) to add context
- If a note looks like a decision (contains "because", "decided", "switching to", "chose", etc.), 
  mark it as [DECISION]
- If a note looks like a blocker ("waiting on", "blocked by", "need", etc.), mark it as [BLOCKER]
- End with a brief "Status" line summarizing where the work stands
- Keep it scannable — someone should get the picture in 30 seconds

Output format:
# Session Logbook — {project_name}
## {date} | {start_time} – {end_time}

### Overview
A short discursive paragraph (3-5 sentences) summarizing what the session was about in plain language.
Write it as flowing prose, not bullet points — e.g., "Today's session focused on setting up the build
pipeline and resolving dependency issues. The engineer started by..."

### Timeline
- **HH:MM** — What happened (context from active apps)
  - [DECISION] Any decisions made and why
  - [BLOCKER] Any blockers encountered

### Decisions Summary
- Bullet list of all decisions with rationale

### Status
One-liner: where does the work stand now?
"""


def check_ollama() -> bool:
    """Check if Ollama is running and the model is available."""
    try:
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        if resp.status_code != 200:
            return False
        models = [m["name"].split(":")[0] for m in resp.json().get("models", [])]
        return OLLAMA_MODEL in models
    except requests.ConnectionError:
        return False


def _trim_events_to_fit(events: list[dict], max_chars: int) -> list[dict]:
    """Downsample capture events if the timeline would exceed max_chars.

    Keeps ALL notes (they're the most valuable). Keeps the first and last
    capture, then evenly samples the rest to fit within the budget.
    """
    note_events = [e for e in events if e["type"] == "note"]
    capture_events = [e for e in events if e["type"] == "capture"]

    # Estimate size: ~80 chars per event line
    estimated_chars = len(events) * 80
    if estimated_chars <= max_chars:
        return events  # fits fine, no trimming needed

    # Budget for captures = total budget minus notes
    notes_chars = len(note_events) * 80
    capture_budget = max(max_chars - notes_chars, 800)  # at least 10 captures
    max_captures = max(capture_budget // 80, 10)

    if len(capture_events) <= max_captures:
        return events  # captures already within budget

    # Evenly sample captures, always keeping first and last
    step = (len(capture_events) - 1) / (max_captures - 1)
    indices = {round(i * step) for i in range(max_captures)}
    sampled_captures = [c for i, c in enumerate(capture_events) if i in indices]

    # Merge notes + sampled captures back in chronological order
    merged = note_events + sampled_captures
    merged.sort(key=lambda e: e["timestamp"])
    return merged


def build_session_context(session_id: int) -> str:
    """Build the prompt context from session data."""
    session = db.get_session(session_id)
    if not session:
        return ""

    notes = db.get_session_notes(session_id)
    captures = db.get_session_captures(session_id)

    # Fetch rich project context, rules, and examples if available
    project = db.get_project(session['project_name'])
    project_context = (project.get("context") or "").strip() if project else ""
    project_rules = (project.get("rules") or "").strip() if project else ""
    project_examples = (project.get("examples") or "").strip() if project else ""

    lines = []
    lines.append(f"Project: {session['project_name']}")
    lines.append(f"Project description: {session.get('project_description', 'N/A')}")
    if project_context:
        lines.append(f"Project context (provided by the engineer — use this to interpret activities more precisely):")
        lines.append(project_context)
    if project_rules:
        lines.append("")
        lines.append("=== PROJECT-SPECIFIC RULES (provided by the engineer — follow these when generating output) ===")
        lines.append(project_rules)
    if project_examples:
        lines.append("")
        lines.append("=== EXAMPLES OF IDEAL LOGBOOK ENTRIES (provided by the engineer — match this style and level of detail) ===")
        lines.append(project_examples)
    lines.append(f"Session start: {session['started_at']}")
    lines.append(f"Session end: {session.get('ended_at', 'ongoing')}")
    lines.append("")

    # Build a merged timeline of notes and captures
    events = []

    for note in notes:
        events.append({
            "timestamp": note["timestamp"],
            "type": "note",
            "content": note["content"],
            "note_type": note["note_type"],
        })

    for cap in captures:
        events.append({
            "timestamp": cap["timestamp"],
            "type": "capture",
            "window": cap.get("active_window", ""),
            "process": cap.get("active_process", ""),
        })

    # Sort by timestamp
    events.sort(key=lambda e: e["timestamp"])

    # Deduplicate consecutive identical captures (just keep transitions)
    filtered_events = []
    last_window = None
    for ev in events:
        if ev["type"] == "note":
            filtered_events.append(ev)
        elif ev["type"] == "capture":
            window_key = f"{ev['window']}|{ev['process']}"
            if window_key != last_window:
                filtered_events.append(ev)
                last_window = window_key

    # Safety cap: if too many events, downsample captures while keeping all notes
    filtered_events = _trim_events_to_fit(filtered_events, max_chars=MAX_CONTEXT_CHARS - len("\n".join(lines)))

    lines.append("=== SESSION TIMELINE ===")
    for ev in filtered_events:
        ts = ev["timestamp"]
        if ev["type"] == "note":
            lines.append(f"[{ts}] NOTE ({ev['note_type']}): {ev['content']}")
        elif ev["type"] == "capture":
            lines.append(f"[{ts}] CONTEXT: {ev['process']} — \"{ev['window']}\"")

    lines.append("")
    lines.append(f"Total notes: {len(notes)}")
    lines.append(f"Total captures: {len(captures)} (showing {sum(1 for e in filtered_events if e['type'] == 'capture')} transitions)")

    return "\n".join(lines)


def _build_summary_payload(session_id: int, stream: bool = False) -> Optional[dict]:
    """Build the Ollama API payload for summary generation. Returns None if session not found."""
    context = build_session_context(session_id)
    if not context:
        return None
    return {
        "model": OLLAMA_MODEL,
        "system": SYSTEM_PROMPT,
        "prompt": f"Generate a structured logbook entry from this session data:\n\n{context}",
        "stream": stream,
        "options": {
            "temperature": 0.3,  # low temperature for factual output
            "num_predict": 2048,
            "num_ctx": OLLAMA_NUM_CTX,
        },
    }


def _format_ollama_error(e: Exception) -> str:
    """Format Ollama errors into user-friendly messages."""
    if isinstance(e, requests.ConnectionError):
        return (
            "Error: Cannot connect to Ollama.\n"
            "  1. Check it's running: ollama list\n"
            "  2. If not installed: https://ollama.com\n"
            "  3. Pull the model: ollama pull " + OLLAMA_MODEL + "\n"
            "See 'FAQ — Failures and How to Fix Them' in the README."
        )
    if isinstance(e, requests.exceptions.ReadTimeout):
        return (
            f"Error: Ollama timed out after {OLLAMA_TIMEOUT}s. The session may be too large for the model.\n"
            "Try a model with a larger context window (e.g., OLLAMA_MODEL=mistral-small),\n"
            "or increase the timeout (OLLAMA_TIMEOUT=600).\n"
            "See 'FAQ — Failures and How to Fix Them' in the README."
        )
    return (
        f"Error generating summary: {e}\n"
        "Your data is safe. Retry with: englog summary <session_id>\n"
        "See 'FAQ — Failures and How to Fix Them' in the README."
    )


def generate_summary(session_id: int) -> str:
    """Generate an AI summary for a session using Ollama (non-streaming)."""
    payload = _build_summary_payload(session_id, stream=False)
    if not payload:
        return "Error: session not found."

    try:
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json=payload,
            timeout=OLLAMA_TIMEOUT,
        )
        resp.raise_for_status()
        result = resp.json()
        summary = result.get("response", "")

        # Save to database
        db.save_session_summary(session_id, summary)
        return summary

    except Exception as e:
        return _format_ollama_error(e)


def generate_summary_stream(session_id: int):
    """Generate an AI summary for a session, yielding tokens as they arrive.

    Yields:
        str: Individual text chunks from the streaming response.

    After iteration completes, the full summary is saved to the database.
    Raises an exception (via a final yield of an error string starting with "Error")
    if something goes wrong.
    """
    payload = _build_summary_payload(session_id, stream=True)
    if not payload:
        yield "Error: session not found."
        return

    try:
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json=payload,
            timeout=OLLAMA_TIMEOUT,
            stream=True,
        )
        resp.raise_for_status()

        full_text = []
        for line in resp.iter_lines():
            if not line:
                continue
            chunk = json.loads(line)
            token = chunk.get("response", "")
            if token:
                full_text.append(token)
                yield token
            if chunk.get("done"):
                break

        summary = "".join(full_text)
        db.save_session_summary(session_id, summary)

    except Exception as e:
        yield _format_ollama_error(e)


def generate_briefing(project_name: str) -> str:
    """Generate a 'here's where you left off' briefing for a project."""
    sessions = db.list_sessions(project_name=project_name, limit=5)
    if not sessions:
        return f"No sessions found for project '{project_name}'."

    # Collect recent summaries and notes
    context_parts = [f"Project: {project_name}", ""]
    for s in reversed(sessions):  # chronological order
        context_parts.append(f"--- Session {s['id']} ({s['started_at']} to {s.get('ended_at', 'ongoing')}) ---")
        if s.get("summary"):
            context_parts.append(f"Summary: {s['summary'][:500]}")
        notes = db.get_session_notes(s["id"])
        for n in notes[-10:]:  # last 10 notes per session
            context_parts.append(f"  [{n['timestamp']}] {n['content']}")
        context_parts.append("")

    briefing_prompt = (
        "Based on the recent session history below, write a concise briefing for the engineer "
        "returning to this project. Answer: What were they working on? What decisions were made? "
        "What's the current status? What are the open items/blockers?\n\n"
        + "\n".join(context_parts)
    )

    payload = {
        "model": OLLAMA_MODEL,
        "system": "You are EngLog. Write a concise project briefing in 5-10 lines. Be specific and actionable.",
        "prompt": briefing_prompt,
        "stream": False,
        "options": {"temperature": 0.3, "num_predict": 1024, "num_ctx": OLLAMA_NUM_CTX},
    }

    try:
        resp = requests.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload, timeout=OLLAMA_TIMEOUT)
        resp.raise_for_status()
        return resp.json().get("response", "")
    except requests.ConnectionError:
        return (
            "Error: Cannot connect to Ollama. Check it's running: ollama list\n"
            "See 'FAQ — Failures and How to Fix Them' in the README."
        )
    except requests.exceptions.ReadTimeout:
        return (
            f"Error: Ollama timed out after {OLLAMA_TIMEOUT}s generating the briefing.\n"
            "See 'FAQ — Failures and How to Fix Them' in the README."
        )
    except Exception as e:
        return (
            f"Error generating briefing: {e}\n"
            "See 'FAQ — Failures and How to Fix Them' in the README."
        )


def generate_project_status(project_name: str) -> str:
    """Generate a concise AI status for a project based on recent sessions.

    Returns a short text describing where the project currently stands:
    what was last worked on, key recent decisions, open blockers, next steps.
    The result is saved to the project's status column.
    """
    project = db.get_project(project_name)
    if not project:
        return f"Project '{project_name}' not found."

    sessions = db.list_sessions(project_name=project_name, limit=5)
    if not sessions:
        return "No sessions recorded yet. Start a session to build project history."

    project_context = (project.get("context") or "").strip()

    context_parts = [f"Project: {project_name}"]
    if project_context:
        context_parts.append(f"Project context: {project_context}")
    context_parts.append("")

    for s in reversed(sessions):  # chronological order
        context_parts.append(f"--- Session {s['id']} ({s['started_at']} to {s.get('ended_at', 'ongoing')}) ---")
        if s.get("summary"):
            context_parts.append(f"Summary: {s['summary'][:800]}")
        notes = db.get_session_notes(s["id"])
        decisions = [n for n in notes if n["note_type"] == "decision"]
        blockers = [n for n in notes if n["note_type"] == "blocker"]
        for n in decisions[-5:]:
            context_parts.append(f"  [DECISION] {n['content']}")
        for n in blockers[-5:]:
            context_parts.append(f"  [BLOCKER] {n['content']}")
        context_parts.append("")

    status_prompt = (
        "Based on the recent session history below, write a concise project status update.\n"
        "Structure your response as:\n"
        "**Last worked on:** What the engineer was doing in the most recent session(s).\n"
        "**Key recent decisions:** The most important decisions made recently (with rationale).\n"
        "**Open blockers:** Anything currently blocking progress (or 'None' if clear).\n"
        "**Current state:** A one-liner summary of where the project stands right now.\n\n"
        "Be specific and concise. Use information from the project context to interpret activities precisely.\n\n"
        + "\n".join(context_parts)
    )

    payload = {
        "model": OLLAMA_MODEL,
        "system": "You are EngLog. Write a concise project status update. Be specific, actionable, and brief.",
        "prompt": status_prompt,
        "stream": False,
        "options": {"temperature": 0.3, "num_predict": 1024, "num_ctx": OLLAMA_NUM_CTX},
    }

    try:
        resp = requests.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload, timeout=OLLAMA_TIMEOUT)
        resp.raise_for_status()
        status_text = resp.json().get("response", "")
        # Cache the status in the database
        db.save_project_status(project_name, status_text)
        return status_text
    except requests.ConnectionError:
        return "Error: Cannot connect to Ollama. Check it's running: ollama list"
    except requests.exceptions.ReadTimeout:
        return f"Error: Ollama timed out after {OLLAMA_TIMEOUT}s."
    except Exception as e:
        return f"Error generating project status: {e}"
