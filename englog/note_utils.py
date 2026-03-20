"""Shared note type auto-detection — used by both CLI and GUI."""


DECISION_KEYWORDS = [
    # Explicit choice verbs
    "decide", "decided", "deciding",
    "choose", "chose", "choosing",
    "select", "selected", "selecting",
    "switch", "switching", "switched",
    "opt", "opting", "opted",
    "prefer", "preferred",
    "approve", "approved",
    "validate", "validated",
    "commit to", "committed to",
    "settle on", "settled on",
    # Phrases that signal a decision
    "going with", "go with", "went with",
    "will go with", "will use",
    "instead of", "rather than", "over the",
    "trade-off", "tradeoff", "trade off",
    "because", "the reason",
    "option a", "option b", "option c",
    "approach a", "approach b",
    "plan a", "plan b",
    "final choice", "final decision",
    "ruled out", "discard",
]

BLOCKER_KEYWORDS = [
    "waiting on", "waiting for",
    "blocked by", "blocked on",
    "can't", "cannot",
    "missing", "stuck",
    "need to get", "need from",
    "depends on", "dependency",
    "no access", "no response",
]


def detect_note_type(content: str) -> str:
    """Auto-detect note type from content keywords.

    Returns:
        "decision" — choices, trade-offs, rationale
        "blocker"  — things blocking progress
        "observation" — everything else (general project notes)
    """
    lower = content.lower()
    if any(kw in lower for kw in DECISION_KEYWORDS):
        return "decision"
    if any(kw in lower for kw in BLOCKER_KEYWORDS):
        return "blocker"
    return "observation"
