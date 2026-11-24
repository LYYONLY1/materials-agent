from contextlib import closing

from fastapi.testclient import TestClient

from materials_agent.api import create_app
from materials_agent.planner import GroundedAnswer, OfflinePlanner, PlannerFailure
from materials_agent.tasks import TaskStore


def test_known_request_bypasses_model_router_and_verifies_quote(tmp_path):
    class UnusedRouter(OfflinePlanner):
        def decide(self, message):
            raise AssertionError("Known intent should not call the planner")

    with TestClient(create_app(tmp_path, start_worker=False, planner=UnusedRouter())) as client:
        run = client.post("/api/runs", json={
            "profile": "verified", "message": "硅的晶体结构是什么？",
        }).json()
    assert run["result"]["citations"] == ["silicon-structure"]
    assert run["result"]["answer"] == run["result"]["evidence"][0]["text"]
    assert run["audit"]["route"] == "rule"
    assert run["audit"]["retrievals"] == 1
    assert run["audit"]["review"] == "verified"


def test_fabrication_with_valid_reference_retries_only_with_new_evidence(tmp_path, monkeypatch):
    original = {"id": "first", "text": "硅在常温常压下采用金刚石立方结构。"}
    alternate = {"id": "second", "text": "硅常见的晶体结构是金刚石立方。"}

    class TwoSources:
        def search(self, query, material, *, mode):
            assert material == "silicon"
            return [original] if mode == "hybrid" else [original, alternate]

    class OneBadDraft(OfflinePlanner):
        def answer(self, message, evidence):
            if evidence == [original]:
                return GroundedAnswer(answer="硅是面心立方金属。", citations=["first"]), {"mode": "test"}
            assert evidence == [alternate]
            return super().answer(message, evidence)

    monkeypatch.setattr("materials_agent.api.configured_index", TwoSources)
    with TestClient(create_app(tmp_path, start_worker=False, planner=OneBadDraft())) as client:
        run = client.post("/api/runs", json={
            "profile": "verified", "message": "硅的晶体结构是什么？",
        }).json()
    assert run["audit"]["retrievals"] == run["audit"]["drafts"] == 2
    assert [step["outcome"] for step in run["trace"] if step["step"] == "verify"] == [
        "unverified_excerpt", "verified",
    ]
    assert run["result"]["answer"] == alternate["text"]
    assert run["result"]["citations"] == ["second"]


def test_no_sources_stops_without_model_draft(tmp_path):
    with TestClient(create_app(tmp_path, start_worker=False)) as client:
        run = client.post("/api/runs", json={
            "profile": "verified", "message": "火星天气",
        }).json()
    assert run["result"]["abstained"]
    assert run["audit"]["retrievals"] == 2
    assert run["audit"]["drafts"] == 0
    assert run["audit"]["model_responses"] == 0


def test_verified_write_requires_approval_and_router_failure_is_read_only(tmp_path):
    class UnavailableRouter(OfflinePlanner):
        def decide(self, message):
            raise PlannerFailure("unavailable")

    request = {"profile": "verified", "message": "提交铝的能量计算"}
    with TestClient(create_app(tmp_path, start_worker=False)) as client:
        pending = client.post("/api/runs", json=request).json()
        assert pending["missing"] == ["approved"]
        path = f"/api/runs/{pending['run_id']}/resume"
        assert client.post(path, json={"approved": False}).json()["result"]["kind"] == "declined"
    with TestClient(create_app(tmp_path, start_worker=False, planner=UnavailableRouter())) as client:
        fallback = client.post("/api/runs", json=request).json()
    assert fallback["audit"]["route"] == "fallback"
    assert fallback["result"]["kind"] == "reference"
    with closing(TaskStore(tmp_path / "tasks.sqlite", readonly=True).connect()) as db:
        assert db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
