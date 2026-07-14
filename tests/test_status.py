"""Tests for the status-summary parser."""
from trcc_monitor.collectors.status import parse_summary


def test_operational():
    body = {
        "status": {"indicator": "none", "description": "All Systems Operational"},
        "incidents": [],
        "scheduled_maintenances": [],
        "components": [],
    }
    out = parse_summary(body)
    assert out["indicator"] == "none"
    assert out["description"] == "All Systems Operational"
    assert out["incidents"] == []


def test_incidents_and_maintenance_filtering():
    body = {
        "status": {"indicator": "minor", "description": "Partial Outage"},
        "incidents": [
            {"name": "API errors", "impact": "minor", "status": "investigating",
             "shortlink": "http://x"},
        ],
        "scheduled_maintenances": [
            {"name": "Done one", "status": "completed"},
            {"name": "Upcoming", "status": "scheduled",
             "scheduled_for": "2026-01-01T00:00:00Z", "scheduled_until": ""},
        ],
        "components": [
            {"name": "API", "status": "operational", "group": False},
            {"name": "Group header", "status": "operational", "group": True},
        ],
    }
    out = parse_summary(body)
    assert len(out["incidents"]) == 1
    assert out["incidents"][0]["name"] == "API errors"
    # completed maintenance filtered out, upcoming kept
    assert len(out["maintenances"]) == 1
    assert out["maintenances"][0]["name"] == "Upcoming"
    # group header filtered out
    assert len(out["components"]) == 1
    assert out["components"][0]["name"] == "API"


def test_missing_keys_default_safely():
    out = parse_summary({})
    assert out["indicator"] == ""
    assert out["incidents"] == []
    assert out["components"] == []


def test_null_lists_tolerated():
    body = {"status": None, "incidents": None, "scheduled_maintenances": None,
            "components": None}
    out = parse_summary(body)
    assert out["incidents"] == []
    assert out["maintenances"] == []
