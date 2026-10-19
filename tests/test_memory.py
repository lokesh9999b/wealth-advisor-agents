"""Tests for the short-term and long-term memory layers."""

from __future__ import annotations

from pathlib import Path

from wealth_advisor.memory.long_term import LongTermMemory
from wealth_advisor.memory.short_term import SessionMemory


def test_short_term_memory_records_facts_notes_events():
    mem = SessionMemory()
    mem.remember("aum", 1000)
    mem.note("looks fine")
    mem.record_event("tool_call", tool="crm_api", ok=True)
    assert mem.recall("aum") == 1000
    assert mem.notes == ["looks fine"]
    assert mem.events[0]["kind"] == "tool_call"
    assert "t" in mem.events[0]


def test_long_term_append_and_get_last(tmp_path: Path):
    store = LongTermMemory(path=tmp_path / "mem.json")
    store.append("C001", {"total_aum": 100, "anomaly_types": ["cash_drag"]})
    store.append("C001", {"total_aum": 150, "anomaly_types": []})
    assert len(store.get_history("C001")) == 2
    assert store.get_last("C001")["total_aum"] == 150
    assert store.get_last("C999") is None


def test_long_term_persists_across_instances(tmp_path: Path):
    path = tmp_path / "mem.json"
    LongTermMemory(path=path).append("C001", {"total_aum": 100})
    # A fresh instance should read what the previous one wrote.
    reloaded = LongTermMemory(path=path)
    assert reloaded.get_last("C001")["total_aum"] == 100


def test_long_term_survives_corrupt_store(tmp_path: Path):
    path = tmp_path / "mem.json"
    path.write_text("{ this is not valid json", encoding="utf-8")
    store = LongTermMemory(path=path)  # should not raise
    assert store.get_history("C001") == []
