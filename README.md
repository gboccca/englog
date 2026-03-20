# EngLog — The Engineering Logbook That Writes Itself

**Capture the flow, not just tasks.**

---

## The Problem

How often have you found yourself wondering "why did I do this? When? How? Was it even me who did it?!"? 
In engineering projects, the logbook is sacred — it's the record of *why* things are the way they are. But nobody keeps it updated. The cognitive cost of stopping your work to document what you're doing is enormous. The result? Traceability is lost. Design reviews become archaeology. When someone asks "why did you choose reaction wheels over CMGs?" three months later, nobody remembers.

This is worse in compliance-driven domains (aerospace, pharma, nuclear, automotive) where the logbook isn't a nice-to-have — it's a regulatory requirement. Engineers spend hours reconstructing what they did after the fact, filling in logbooks from memory, emails, and guesswork.

## The Solution

EngLog runs quietly while you work. It captures your screen context (which apps, files, and windows you have open), lets you drop quick timestamped notes when you make decisions (commercially available LLM solutions still can't read your mind), and at the end of each work session, an LLM generates a structured logbook entry automatically — complete with a timeline, decision summary, and status update.

The core value is **passivity**. The tool requires near-zero effort to produce a 90% complete logbook. Your manual notes are the cherry on top, not the foundation.

After a month of use, you have a searchable, structured history of *every decision and its rationale*. A new team member joins? "Read the logbook." A reviewer asks why you chose X over Y? The answer is there, dated, with context.

## What Makes EngLog Different

- **It's not Notion or Obsidian.** Those require discipline and manual input. EngLog works even if you never type a single note — the passive screen capture alone produces useful output.
- **It's not a time tracker.** RescueTime tells you that you spent 3 hours in Excel. EngLog tells you that you spent 3 hours in `CMG_trade_v2.xlsx` and decided to reduce from 4 to 3 CMGs because the redundancy analysis showed acceptable risk at the target orbit inclination.
- **It's not surveillance.** Everything runs locally on your machine. Screenshots never leave your disk. The AI (Ollama) runs locally. No cloud, no telemetry, no employer dashboards. This is *your* logbook.
- **It's built for engineers.** The AI understands engineering workflows — decisions with rationale, trade-offs, blockers, compliance tracing. It produces output you'd actually want in a design review package.

---

## Quick Start

### Prerequisites

1. **Python 3.10+** — check with `python --version`
2. **Ollama** — local AI runtime. Install from [ollama.com](https://ollama.com), then pull a model:
   ```bash
   ollama pull mistral
   ```
   Ollama runs in the background automatically after install.

### Install EngLog

```bash
git clone <repo-url>
cd englog
pip install -e .
```

> **Windows note:** if `englog` is not recognized after install, add Python's Scripts directory to your PATH:
> ```powershell
> # Find the path:
> python -c "import sysconfig; print(sysconfig.get_path('scripts', 'nt_user'))"
> # Add it (temporary, current session):
> $env:Path += ";C:\Users\<you>\AppData\Roaming\Python\Python3xx\Scripts"
> # Add it (permanent):
> [Environment]::SetEnvironmentVariable("Path", [Environment]::GetEnvironmentVariable("Path", "User") + ";C:\Users\<you>\AppData\Roaming\Python\Python3xx\Scripts", "User")
> ```
> Restart your terminal after the permanent fix.

### Your First Session — GUI (recommended)

Launch the GUI:
```bash
englog-gui
```

A small floating panel opens with five tabs:

1. **Session** — Type a project name, click **Start Session**. The capture daemon starts automatically (screenshots + active window tracking). Add notes in the text field — type detection is shown live as you type. Click **Stop Session** when done.
2. **Project** — Select a project and configure how the AI interprets your sessions. Three sub-tabs:
   - **Context** — describe what the project is about (the AI uses this to produce more precise summaries)
   - **Rules (optional)** — add project-specific rules for the AI (e.g. "always mention file names", "distinguish meetings from solo work", "write in French")
   - **Examples (optional)** — paste examples of ideal logbook entries — the AI will match this style and level of detail

   Also shows an AI-generated **project status** — a snapshot of where the project currently stands, based on recent sessions.
3. **History** — Browse past sessions, filter by project, search across all notes.
4. **Summary** — Select a session, click **Generate Summary** to get an AI logbook entry. Click **Export XLSX** to generate a formatted timesheet. Click **Open File** to view it in Excel.
5. **Settings** — Check Ollama connection status, switch models, adjust screenshot interval and quality.

The GUI stays on top of your other windows so you can drop notes without alt-tabbing away from your work.

### Your First Session — CLI (alternative)

You'll use **two terminals**: one for the capture daemon, one for everything else.

**Terminal 1 — Start a session:**
```bash
englog start "my-project" -d "Brief description of the project"
```
This starts the capture daemon (screenshots every 30 seconds + active window tracking). Keep this terminal open while you work.

**Terminal 2 — Work and take notes:**
```bash
# Drop notes whenever you make a decision or hit a milestone:
englog note "reviewed thermal model — assumptions look conservative"
englog note "decided to increase safety margin to 1.5 because of altitude uncertainty"
englog note "waiting on FEA results from Pierre before finalizing bracket design"

# Check what you've captured so far:
englog status
```

**Terminal 2 — End of day, stop and get your logbook:**
```bash
englog stop
```
This does three things automatically:
1. Stops the session and marks it complete
2. Sends your notes + screen activity to the local AI — generates a **narrative summary**
3. Sends the same data to the AI again — generates a **structured xlsx timesheet** with 30-minute blocks

Both outputs are saved permanently and can be retrieved anytime.

### Standalone Executable (no Python required)

You can also build a standalone `EngLog.exe` with PyInstaller:
```bash
pyinstaller englog.spec --clean
```
The output is `dist/EngLog.exe` — a single-file GUI application with no console window. Ollama still needs to be installed separately.

---

## Full Command Reference (CLI)

### Session Management

| Command | What it does |
|---------|-------------|
| `englog start <project> [-d "description"]` | Start a new session. Launches the capture daemon in the current terminal. |
| `englog stop` | Stop the active session. Auto-generates AI summary + xlsx timesheet. |
| `englog resume` | Restart the capture daemon for an active session (after closing the terminal). |
| `englog status` | Show current session info: project, duration, note count, recent notes. |

**Lifecycle details:**
- `englog start` creates a new session and begins capturing. The terminal becomes the capture process — keep it open.
- If you close the terminal (or your laptop), the **capture stops but the session stays active**. Your notes still work from any terminal.
- When you reopen, `englog resume` detects the active session and restarts capture from where you left off.
- If a session gets orphaned (e.g., crash), `englog resume` finds it and asks what you want to do.
- `englog stop` finalizes everything. You can only have **one active session at a time**.
- The GUI handles all of this automatically — it detects orphaned sessions on startup and resumes capture.

### Note-Taking

| Command | What it does |
|---------|-------------|
| `englog note "your text here"` | Add a timestamped note to the active session. |
| `englog note -t decision "chose X because Y"` | Force a specific note type. |

**Note types are auto-detected** from your language:
- **DECISION** — triggered by: "because", "decided", "switching to", "chose", "going with", "trade-off", "instead of"
- **BLOCKER** — triggered by: "waiting on", "blocked by", "need", "can't", "missing", "stuck"
- **OBSERVATION** — everything else

You can override with `-t decision`, `-t blocker`, or `-t observation`, but the auto-detection is good enough for most cases. Just write naturally. In the GUI, the detected type is shown live as you type.

**Tips for effective notes:**
- Bias toward **decisions with rationale**: "Switching from X to Y because Z" is the most valuable thing you can log.
- Don't narrate every action: "Opened Excel" is noise. "Updated mass budget — 3-CMG config saves 1.2 kg" is gold.
- Blockers help future-you: "Waiting on thermal data from Pierre" means next week you know exactly what's holding things up.
- Speed matters: the note should take <10 seconds. If you're writing a paragraph, you're overthinking it.

### AI Outputs

| Command | What it does |
|---------|-------------|
| `englog summary [session_id]` | Show the AI narrative summary (uses cached version if available). |
| `englog briefing <project>` | "Where did I leave off?" — AI summary of recent sessions on a project. |
| `englog export [session_id] [-o path]` | Generate/regenerate the xlsx timesheet for a session. |

All of these are also available in the GUI's **Summary** tab with clickable buttons.

**The narrative summary** is a structured logbook entry: timeline of activities, highlighted decisions with rationale, blockers, and a status line. It reads like what a diligent engineer would write at the end of the day — except it's generated in 20 seconds.

**The briefing** is for when you return to a project after days or weeks away. It reads the last 5 sessions and tells you: what you were working on, what decisions were made, what's the current status, and what's still open.

**The xlsx timesheet** is a formatted spreadsheet with three sheets:
1. **Timesheet** — 30-minute window blocks with task title + description. Duration is calculated (first/last blocks may be partial). Each window gets one primary activity.
2. **Notes** — all your raw notes, color-coded by type (purple=decision, red=blocker, blue=observation).
3. **AI Summary** — the full narrative summary text.

The xlsx is saved in `~/.englog/exports/` by default, or wherever you specify with `-o`.

### Search and History

| Command | What it does |
|---------|-------------|
| `englog history [-p project] [-n count]` | List past sessions with stats. |
| `englog search "query" [-p project]` | Full-text search across all notes, all sessions, all projects. |
| `englog projects` | List all projects with session counts. |

**Search is powerful.** `englog search "margin"` finds every note you ever wrote mentioning margins, across all projects. `englog search "thermal" -p MAES2SolarEx` narrows it to one project. Results show timestamp, project, note type, and content.

The GUI's **History** tab provides the same search functionality with a graphical interface.

### System Tray

| Command | What it does |
|---------|-------------|
| `englog tray` | Launch the system tray icon (Windows). Shows green=recording, gray=idle. |

The tray icon is an alternative to keeping a terminal open. It runs the capture daemon in the background and shows status in your taskbar. You can stop the session from the tray menu.

---

## How It Works Under the Hood

### Data Flow

```
+----------------------------------------------------------------------+
|                        YOUR WORK SESSION                             |
|                                                                      |
|   You work normally on your computer                                 |
|   +-- Apps you use, files you open, windows you switch between       |
|   +-- Quick notes via GUI panel or CLI ("englog note ...")           |
|                                                                      |
+----------------------------------------------------------------------+
|                        ENGLOG CAPTURES                               |
|                                                                      |
|   Every 30 seconds (configurable via Settings or config.py):         |
|   +-- Screenshot (compressed JPEG, half-resolution, ~50-100 KB)      |
|   +-- Active window title (e.g., "CMG_trade_v2.xlsx - Excel")        |
|   +-- Active process name (e.g., "EXCEL.EXE")                        |
|                                                                      |
|   On every note (GUI "Add" button or "englog note" command):         |
|   +-- Note content + timestamp                                       |
|   +-- Auto-detected type (decision/blocker/observation)              |
|   +-- Stored in SQLite database                                      |
|                                                                      |
+----------------------------------------------------------------------+
|                        AI SYNTHESIS (on session stop)                 |
|                                                                      |
|   1. Narrative Summary:                                              |
|      +-- Merges notes + screen activity into timeline                |
|      +-- Deduplicates captures (only keeps app transitions)          |
|      +-- Sends to Ollama (local LLM) with engineering-specific       |
|      |   system prompt                                               |
|      +-- Outputs: structured logbook entry with decisions,           |
|          timeline, blockers, status                                  |
|                                                                      |
|   2. Timesheet:                                                      |
|      +-- Pre-computes fixed 30-min window grid                       |
|      +-- Calculates real active minutes per window                   |
|      +-- Sends windows + timeline to Ollama                          |
|      +-- AI fills in task title + description per window             |
|      +-- Outputs: formatted .xlsx with Timesheet + Notes +           |
|          Summary sheets                                              |
|                                                                      |
+----------------------------------------------------------------------+
|                        STORED PERMANENTLY                            |
|                                                                      |
|   ~/.englog/                                                         |
|   +-- englog.db          <- SQLite: projects, sessions, notes,       |
|   |                        captures metadata, AI summaries           |
|   +-- screenshots/                                                   |
|   |   +-- 1/             <- Session 1 screenshots                    |
|   |   +-- 2/             <- Session 2 screenshots                    |
|   |   +-- ...                                                        |
|   +-- exports/                                                       |
|       +-- englog_myproject_20260415_s3.xlsx                           |
|       +-- ...                                                        |
|                                                                      |
|   Nothing ever leaves your machine.                                  |
+----------------------------------------------------------------------+
```

### Database Schema

Four tables in SQLite (`englog.db`):

- **projects** — `id`, `name` (unique), `description`, `context` (user-written project details for AI), `rules` (optional AI rules), `examples` (optional ideal entry examples), `status` (AI-generated project status), `created_at`
- **sessions** — `id`, `project_id` (FK), `started_at`, `ended_at`, `summary` (AI text), `is_active`
- **notes** — `id`, `session_id` (FK), `timestamp`, `content`, `note_type` (decision/blocker/observation)
- **captures** — `id`, `session_id` (FK), `timestamp`, `screenshot_path`, `active_window`, `active_process`

### The AI Layer

EngLog uses **Ollama** to run open-source LLMs 100% locally. No API keys, no cloud, no cost per query.

Two separate AI calls happen per session:

1. **Narrative summary** (`summary.py` → `SYSTEM_PROMPT`) — receives the full merged timeline (notes + deduplicated app transitions) and generates a prose logbook entry. The system prompt instructs the model to write in past tense, highlight decisions as `[DECISION]`, flag blockers as `[BLOCKER]`, and end with a status line.

2. **Timesheet generation** (`export.py` → `TIMESHEET_SYSTEM_PROMPT`) — receives the same timeline PLUS a pre-computed list of 30-minute windows with active durations. The model must return structured JSON with exactly those windows filled in. The code validates and merges the AI output back onto the pre-computed grid, so even if the model hallucinates extra windows or changes times, the final xlsx is always structurally correct.

**Improving AI quality:**

The single biggest lever is the system prompt. After a few real sessions, edit `SYSTEM_PROMPT` in `summary.py` and `TIMESHEET_SYSTEM_PROMPT` in `export.py` — add examples of ideal output based on your actual sessions.

The second lever is the model. You can switch models in the GUI's Settings tab, or try different ones from the command line:
```bash
ollama pull llama3.1          # 8B, strong at structured output
ollama pull gemma2            # 9B, good at following instructions
ollama pull mistral-small     # 22B, much smarter, needs 16GB+ RAM
ollama pull qwen2.5           # 7B, surprisingly good at technical content
```
Switch with: `set OLLAMA_MODEL=llama3.1` (Windows) or edit `config.py`, or use the GUI Settings tab.

---

## Configuration

All settings are in `englog/config.py` and can be overridden via environment variables. Screenshot interval, quality, and model can also be changed at runtime in the GUI's **Settings** tab (applies to the next session, not persisted across restarts).

| Setting | Default | Env Var | Description |
|---------|---------|---------|-------------|
| Data directory | `~/.englog` | `ENGLOG_DATA` | Where the DB, screenshots, and exports live |
| Screenshot interval | 30 seconds | — | How often to capture (edit `config.py` or GUI Settings) |
| Screenshot quality | 40 (JPEG) | — | Lower = smaller files, 40 is plenty |
| Screenshot scale | 0.5 | — | Half resolution, saves ~75% disk space |
| Ollama URL | `http://localhost:11434` | `OLLAMA_BASE_URL` | Change if Ollama runs on a different port |
| Ollama model | `mistral` | `OLLAMA_MODEL` | Any model you've pulled with `ollama pull` |
| Context window | 32768 | `OLLAMA_NUM_CTX` | Increase for very long sessions (needs more RAM) |
| Timeout | 300 seconds | `OLLAMA_TIMEOUT` | How long to wait for Ollama to respond |

### Disk Usage Estimates

| Session length | Screenshots (~80KB each) | Database | Total |
|---|---|---|---|
| 1 hour | ~120 screenshots = 10 MB | <1 MB | ~10 MB |
| 8 hours | ~960 screenshots = 77 MB | <1 MB | ~80 MB |
| 1 month (20 days x 8h) | ~19,200 screenshots = 1.5 GB | ~5 MB | ~1.5 GB |

Adjust screenshot interval (e.g., 60s = half the storage) or quality (e.g., 25 = even smaller files) in the GUI Settings tab or in `config.py`.

---

## Customisation Guide

EngLog is designed so that the parts you'd want to tweak are cleanly separated from the structural code. This section covers every tunable part — what it does, where to find it, and when to change it.

### 1. AI Prompts — Per-Project Rules and Examples (easiest)

The fastest way to improve AI output for a specific project is to use the **Project** tab in the GUI. Select your project and use the sub-tabs:

- **Rules** — Add project-specific instructions, e.g.:
  - "Always mention file names visible in window titles"
  - "Distinguish between meetings (Teams/Zoom) and solo work"
  - "Write the summary in French"
  - "Include the CATIA part number when visible"
- **Examples** — Paste 1-2 examples of ideal logbook entries from your best sessions. The AI will match this style and level of detail.

These are optional — the built-in system prompt is already enough for most use cases. But for technical/domain-specific projects, adding rules and examples dramatically improves quality.

Everything you enter is auto-saved and injected into the AI prompt every time a summary or xlsx is generated for that project.

### 2. AI System Prompts — Global (advanced)

If you want to change the AI's behaviour across *all* projects, edit the hard-coded system prompts:

#### Narrative Summary Prompt

**File:** `englog/summary.py` (`SYSTEM_PROMPT`)

**What it controls:** The format, tone, and structure of the logbook entry generated on session stop or via "Generate Summary".

**When to change it:**
- If the output format doesn't match what you need globally (e.g., your team expects a different logbook structure, or compliance requires specific fields), rewrite the `Output format:` section.
- If the AI produces too much filler or not enough detail, adjust the tone instructions.
- For project-specific tweaks, prefer the GUI's Project tab Rules/Examples instead of editing this file.

Adding 1-2 real examples from your best sessions dramatically improves consistency.

#### Timesheet Prompt

**File:** `englog/export.py` (`TIMESHEET_SYSTEM_PROMPT`)

**What it controls:** How the AI classifies tasks in each 30-minute window of the xlsx timesheet. The prompt maps process names to activities (e.g., `EXCEL.EXE -> spreadsheet work`).

**When to change it:**
- If you use domain-specific software that the AI doesn't recognise. For example, if you use CATIA, MATLAB, Simulink, or STK, add mappings.
- If the task titles are too vague. Add a rule like: "Always include the document or file name when visible in the window title."
- If you want the AI to distinguish between meetings (Teams/Zoom) and solo work.

**What NOT to change in this prompt:** The JSON output format specification and the `CRITICAL: You must return EXACTLY the windows provided` instruction. These ensure the AI output can be parsed and merged onto the pre-computed time grid.

### 3. AI Model and Parameters

#### Model Selection

**File:** `englog/config.py` — or set `OLLAMA_MODEL` environment variable — or use the GUI Settings tab.

| Model | Size | RAM needed | Best for |
|---|---|---|---|
| `mistral` (default) | 7B | ~8GB | General-purpose, good default |
| `llama3.1` | 8B | ~8GB | Reliable structured JSON output |
| `gemma2` | 9B | ~8GB | Following detailed instructions |
| `qwen2.5` | 7B | ~8GB | Technical/engineering content |
| `mistral-small` | 22B | ~16GB | Best quality, slower |

#### Temperature

**Files:** `englog/summary.py` and `englog/export.py`

- **Summary temperature** (`0.3`): Controls how creative vs. factual the narrative is. Lower (0.1-0.2) = more repetitive but sticks closer to the data. Higher (0.4-0.6) = more readable prose but might embellish.
- **Timesheet temperature** (`0.2`): Should stay low. The timesheet needs precision, not creativity.

**Rule of thumb:** If the AI is hallucinating facts, lower the temperature. If it's producing boring, repetitive output, raise it slightly.

### 4. Note Type Auto-Detection Keywords

**File:** `englog/note_utils.py`

```python
# Decision keywords:
["because", "decided", "switching", "chose", "going with", "trade-off", "instead of"]

# Blocker keywords:
["waiting", "blocked", "need", "can't", "missing", "stuck"]

# Everything else -> observation
```

**When to change it:**
- If notes you consider decisions are being classified as observations — add your domain's decision language (e.g., `"validated"`, `"approved"`, `"selected"`, `"opting for"`).
- If you want to add a new note type entirely (e.g., `"milestone"` or `"risk"`), you need to update: (1) `note_utils.py`, (2) `TYPE_COLORS` in `gui.py`, (3) `type_colors` in `export.py`, (4) optionally the AI system prompts.

### 5. Screenshot Capture Settings

**File:** `englog/config.py` — or use the GUI Settings sliders.

| Setting | Default | Trade-off |
|---|---|---|
| `SCREENSHOT_INTERVAL_SECONDS` | `30` | Lower = more granular but more disk usage. `60` halves storage. |
| `SCREENSHOT_QUALITY` | `40` | JPEG quality 1-100. `40` is surprisingly readable. `70` looks great but 3x larger. |
| `SCREENSHOT_SCALE` | `0.5` | Resize factor. `0.5` = half resolution (saves ~75% space). |

### 6. Note Type Colors in xlsx

**File:** `englog/export.py` (`type_colors` dict)

```python
type_colors = {
    "decision": PatternFill("solid", fgColor="E8D5F5"),   # light purple
    "blocker":  PatternFill("solid", fgColor="FCDEDE"),    # light red
    "observation": PatternFill("solid", fgColor="DEEAF6"), # light blue
}
```

The GUI uses its own `TYPE_COLORS` dict in `gui.py` for the note display.

---

## Platform Support

| Feature | Windows | macOS | Linux |
|---------|---------|-------|-------|
| GUI application | ✅ | ✅ | ✅ |
| CLI commands | ✅ | ✅ | ✅ |
| Screenshots | ✅ | ✅ | ✅ |
| Active window title | ✅ (pywin32) | ⚠ (fallback: "unknown") | ⚠ (fallback: "unknown") |
| System tray icon | ✅ | ✅ | ✅ |
| Standalone .exe build | ✅ | — | — |

Active window detection currently uses `pywin32` on Windows. On macOS/Linux it degrades gracefully to "unknown" — the screenshots and notes still work perfectly. Adding native macOS (`AppKit`) and Linux (`xdotool`) support is a planned enhancement.

---

## Project Structure

```
englog/
├── pyproject.toml          <- Package config, dependencies, entry points
├── englog.spec             <- PyInstaller config for standalone EngLog.exe
├── README.md               <- This file
├── CLAUDE.md               <- Instructions for AI coding assistants (Claude Code)
├── .gitignore
│
└── englog/                 <- Source package
    ├── __init__.py         <- Version string
    ├── config.py           <- All settings (paths, intervals, model, env vars)
    ├── database.py         <- SQLite schema + all CRUD operations (4 tables)
    ├── capture.py          <- Screenshot + active window tracking (background thread)
    ├── session.py          <- Session lifecycle (start/stop/resume, pidfile management)
    ├── note_utils.py       <- Shared note type auto-detection (used by GUI + CLI)
    ├── summary.py          <- AI narrative summary generation via Ollama
    ├── export.py           <- AI timesheet generation + xlsx builder (openpyxl)
    ├── gui.py              <- CustomTkinter GUI (5 tabbed views)
    ├── cli.py              <- Click CLI: all user-facing terminal commands
    ├── tray.py             <- System tray icon (pystray, Windows)
    └── utils/              <- (Reserved for future utilities)
```

---

## FAQ — Failures and How to Fix Them

### "AI summary generation failed" when stopping a session

**What happened:** The AI call to Ollama timed out or the prompt exceeded the model's context window. This is most common after long sessions (several hours) with many screen captures.

**What to do:**
1. Your notes and captures are **safe in the database** — nothing is lost.
2. Re-run the summary: use the GUI Summary tab and click "Generate Summary", or run `englog summary <session_id>`.
3. Re-run the export: use "Export XLSX" in the GUI, or run `englog export <session_id>`.
4. If it keeps failing, try a model with a larger context window:
   ```bash
   ollama pull mistral-small
   set OLLAMA_MODEL=mistral-small
   ```
   Or switch models in the GUI Settings tab.

### "Ollama not running or model not found"

**What happened:** Ollama wasn't running when you tried to generate a summary, or the configured model hasn't been pulled.

**What to do:**
1. Check Ollama is running: `ollama list` — if it errors, Ollama isn't running.
2. Pull the model: `ollama pull mistral`
3. In the GUI, go to Settings and click "Refresh" to check the connection.

**Note:** Even when Ollama is unavailable, stopping a session still produces an xlsx file with the correct time grid and your notes — only the AI task descriptions will show "(Fill manually)".

### The xlsx was generated but has "Unclassified" in every row

**What happened:** The AI timesheet call failed, so the export fell back to placeholder text. The time grid and notes sheets are still correct.

**What to do:**
1. Re-run: click "Export XLSX" in the GUI Summary tab, or run `englog export <session_id>`.
2. If it fails again, check that Ollama is running and that you have enough RAM for the model.
3. You can also fill in the task descriptions manually — the time windows and durations are always accurate.

### I closed the GUI / terminal mid-session — is my data lost?

**No.** Closing the window or terminal only stops the **capture daemon** (screenshots + active window tracking). The session stays active, and you can still add notes. When you relaunch the GUI, it detects the active session and resumes capture automatically. From the CLI, run `englog resume`.

### The database keeps growing — will it slow down?

The SQLite database handles millions of rows without performance issues. The main storage concern is **screenshots on disk** (~25 MB per 5-hour session, ~1.5 GB per month of daily 8-hour use). Adjust screenshot interval or quality in the GUI Settings tab or in `config.py`.

---

## Roadmap / Known Limitations

**Current limitations (v0.2.0):**
- Active window detection only works on Windows (macOS/Linux degrade to "unknown")
- GUI settings are not persisted across restarts (model choice, interval, quality reset to defaults)
- No multi-user / team features — this is a solo tool for now
- Ollama must be installed separately

**Planned improvements - order of priority:**

1. ~~create fake but realistic example data for a fictitious project, to generate a sample "demo" summary on~~ **Done** — `englog demo` creates a realistic aerospace engineering project (SolarSailNav) with 20 notes (decisions, blockers, observations), 30 capture transitions, and project context/rules. Ready for `englog summary` and `englog export`. Remove with `englog delete-project SolarSailNav`.
2. ~~add a better management system of various projects/sessions (can delete/rename/manually modify projects/entries if needed)~~ **Done** — GUI: Rename/Delete buttons on Project tab, Delete button on each session card in History tab. CLI: `englog rename-project`, `englog delete-project`, `englog delete-session`. All deletions cascade (notes, captures, screenshots) with confirmation prompts. Active sessions are protected.
3. ~~Global hotkey for instant note capture (no window switch needed) and classify notes into [OBSERVATIONS]/[DECISIONS]/[GENERAL]~~ **Done** — **Ctrl+Shift+N** opens a small floating popup from any application. Type your note, see live type detection (decision/blocker/observation), press Enter. The popup saves the note and closes automatically. No window switching needed. Uses the `keyboard` library for system-wide hotkey registration.
4. ~~How to halt a session? I think i'd add a "pause" button to first GUI tab; if I close to gui though? should work as well... though less "clean". Also connected to that, add extensive verification... unit tests. other ways to verify code works and absence of bugs?~~ **Done** — (A) Orange **Pause** button appears next to Stop during active sessions. Pausing stops screen capture but keeps the session active (notes still work, timer keeps running). Button toggles to green **Resume** to restart capture. (B) **72 unit tests** across 4 test files covering database CRUD, project/session management, note type detection, session lifecycle, and summary context building. Run with `pytest tests/`.
5. ~~"recent notes" window in first tab of the GUI is useless i find... how could we make that space worth? what could go there? Also, add a color to the top navigation bar (that with all the tabs)~~ **Done** — (A) Navigation bar now has a dark blue (`#2B4C8C`) background with white active tab text and a white underline indicator. (B) "Recent Notes" replaced with a hybrid panel: during active sessions, shows a **live activity feed** merging notes and app transitions (captures) in a unified timeline; when idle, shows a **dashboard** with today/week hours, streak counter, weekly stats (sessions, notes, decisions), top apps, and recent sessions with quick "View" buttons.
6. ~~Persistent settings (save GUI preferences to disk)~~
7. Possibility to select Markdown/PDF export of narrative summaries (in general, customisation of output)
8. macOS and Linux active window detection
9. Multi-user / team logbooks with cross-referencing
10. Cloud API fallback (Claude/GPT) for users who don't want to run Ollama
11. Few-shot prompt injection (use your best past summaries as examples for the AI)

---

## License

MIT
