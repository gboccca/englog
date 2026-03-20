"""Tests for note type auto-detection."""

import pytest
from englog.note_utils import detect_note_type


class TestDecisionDetection:
    @pytest.mark.parametrize("text", [
        "decided to use LQR controller",
        "choose the 3-panel config",
        "chose aluminium over titanium",
        "going with reaction wheels instead of CMGs",
        "will go with option A for thermal design",
        "switching to Python for the analysis",
        "selected the 45-day transfer",
        "opting for the redundant design",
        "approved the final bracket design",
        "validated the simulation results",
        "prefer approach B — simpler",
        "ruled out carbon fiber for cost reasons",
        "committed to the 3-axis stabilisation",
        "we went with the cheaper option because of budget",
        "trade-off between mass and redundancy",
    ])
    def test_detects_decision(self, text):
        assert detect_note_type(text) == "decision"


class TestBlockerDetection:
    @pytest.mark.parametrize("text", [
        "waiting on thermal data from Marie",
        "blocked by IT — no license",
        "stuck on convergence issue",
        "can't proceed without FEA results",
        "missing the test report",
        "depends on Pierre's review",
    ])
    def test_detects_blocker(self, text):
        assert detect_note_type(text) == "blocker"


class TestObservationDetection:
    @pytest.mark.parametrize("text", [
        "reviewed the mass budget spreadsheet",
        "Monte Carlo batch running overnight",
        "updated the PDR slides",
        "team meeting at 2pm",
        "lunch break",
        "committed code to repo",
    ])
    def test_detects_observation(self, text):
        assert detect_note_type(text) == "observation"


def test_case_insensitive():
    assert detect_note_type("DECIDED to use X") == "decision"
    assert detect_note_type("WAITING ON data") == "blocker"
