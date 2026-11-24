import asyncio
import json
import os
import sys
from contextlib import closing

from fastapi.testclient import TestClient
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from materials_agent.api import create_app
from materials_agent.evaluation import evaluate
from materials_agent.planner import GroundedAnswer, OfflinePlanner
from materials_agent.retrieval import INDEX, markdown_chunks
from materials_agent.tasks import TaskStore


def test_retrieval_ranks_bilingual_phrases_and_limits_scope():
    hits = INDEX.search("crystal structure of aluminum", "aluminum")
    assert hits[0]["id"] == "aluminum-structure"
    assert all(item["material"] in {"aluminum", None} for item in hits)
    assert INDEX.search("铝是什么元素", "aluminum")[0]["id"] == "aluminum-identity"
    assert INDEX.search("火星天气") == []
    assert INDEX.search("annual rainfall in Tokyo") == []


def test_information_request_does_not_enqueue_calculation(tmp_path):
    with TestClient(create_app(tmp_path, start_worker=False)) as client:
        run = client.post("/api/runs", json={"message": "模拟评分会有能量单位吗？"}).json()
        assert run["result"]["citations"] == ["guide-energy"]
        assert "没有能量单位" in run["result"]["answer"]
        unknown = client.post("/api/runs", json={"message": "火星天气"}).json()
        assert unknown["result"]["abstained"] is True
        assert unknown["trace"][-1]["metrics"]["mode"] == "skipped"
        assert client.get("/api/knowledge/search", params={"q": "工具超时"}).json()["hits"][0]["id"] == "guide-retry"


def test_markdown_import_preserves_heading_and_returns_citation(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "Lab.md").write_text(
        "# 样品编号\n\n硼污染检查样品编号为 B076。\n\n## 原始记录\n\n" + "应力记录。" * 200,
        encoding="utf-8",
    )
    monkeypatch.setenv("MATERIALS_KNOWLEDGE_DIR", str(corpus))
    with TestClient(create_app(tmp_path / "state", start_worker=False)) as client:
        result = client.post("/api/runs", json={"message": "硼污染检查样品编号是什么？"}).json()["result"]
        assert result["citations"] == ["md:Lab.md:1"]
        assert "B076" in result["answer"]
        assert result["evidence"][0]["title"] == "Lab · 样品编号"


def test_markdown_index_skips_empty_sections(tmp_path):
    source = tmp_path / "Lab.md"
    source.write_text("# 空标题\n\n## 测量记录\n\n样品编号 B076。\n\n## 结束\n", encoding="utf-8")
    chunks = markdown_chunks(source)
    assert [(chunk.title, chunk.text) for chunk in chunks] == [("Lab · 测量记录", "样品编号 B076。")]


def test_unknown_citation_is_rejected(tmp_path):
    class InvalidCitationPlanner(OfflinePlanner):
        def answer(self, message, evidence):
            return GroundedAnswer(answer="Unsupported claim", citations=["fake"]), {"mode": "test"}

    with TestClient(create_app(tmp_path, planner=InvalidCitationPlanner())) as client:
        run = client.post("/api/runs", json={"message": "硅是什么"}).json()
        assert run["result"]["abstained"] is True
        assert run["result"]["citations"] == []
        assert "Unsupported claim" not in run["result"]["answer"]


def test_approval_decline_and_restart(tmp_path):
    request = {"message": "提交铝的能量计算", "require_approval": True}
    with TestClient(create_app(tmp_path, start_worker=False)) as client:
        paused = client.post("/api/runs", json=request).json()
        assert paused["missing"] == ["approved"]
        assert paused["pending_parameters"]["material"] == "aluminum"
        url = f"/api/runs/{paused['run_id']}"
        assert client.post(f"{url}/resume", json={"approved": "true"}).status_code == 422
    store = TaskStore(tmp_path / "tasks.sqlite")
    with closing(store.connect()) as db:
        assert db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0

    with TestClient(create_app(tmp_path, start_worker=False)) as client:
        assert client.get(url).json()["missing"] == ["approved"]
        declined = client.post(f"{url}/resume", json={"approved": False}).json()
        assert declined["result"] == {"kind": "declined"}
        assert declined["trace"][-1]["approved"] is False
        second = client.post("/api/runs", json=request).json()
        accepted = client.post(f"/api/runs/{second['run_id']}/resume", json={"approved": True}).json()
        assert accepted["result"]["kind"] == "task"
    with closing(store.connect()) as db:
        assert db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1


def test_sse_cursor_replays_only_remaining_events(tmp_path):
    with TestClient(create_app(tmp_path, start_worker=False)) as client:
        store = TaskStore(tmp_path / "tasks.sqlite")
        task = store.submit("sse-test", "silicon", "energy", "normal")
        claim = store.claim()
        store.finish(claim, result={"simulation": True})
        cursor = store.get(task)["events"][0]["id"]
        result = client.get(f"/api/tasks/{task}/events", headers={"Last-Event-ID": str(cursor)})
        assert result.headers["content-type"].startswith("text/event-stream")
        assert result.text.count("event: task_event") == 2
        events = [json.loads(line.removeprefix("data: ")) for line in result.text.splitlines()
                  if line.startswith("data: ")]
        assert [item.get("event") for item in events] == ["started", "succeeded", None]
        assert events[-1] == {"status": "succeeded"}


def test_event_stream_replays_multiple_pages_before_terminal_event(tmp_path):
    with TestClient(create_app(tmp_path, start_worker=False)) as client:
        store = TaskStore(tmp_path / "tasks.sqlite")
        task_id = store.submit("sse-pages", "iron", "energy", "normal")
        claim = store.claim()
        first_events = store.get(task_id)["events"]
        with store.write() as db:
            for number in range(54):
                store.event(db, task_id, "progress", 1, number)
        store.finish(claim, result={"simulation": True})
        response = client.get(f"/api/tasks/{task_id}/events?after={first_events[0]['id']}",
                              headers={"Last-Event-ID": str(first_events[1]["id"])})
        assert response.status_code == 200
        assert response.text.count("event: task_event") == 55
        assert response.text.index('"event": "succeeded"') < response.text.index("event: done")


def test_research_calculation_persists_evidence_and_requires_approval(tmp_path):
    message = "先查硅的资料，再提交能量计算"
    with TestClient(create_app(tmp_path, start_worker=False)) as client:
        paused = client.post("/api/runs", json={"message": message}).json()
        assert paused["missing"] == ["approved"]
        assert [step["step"] for step in paused["trace"]] == ["plan", "retrieve"]
        assert {item["id"] for item in paused["pending_evidence"]} >= {"silicon-identity"}
        url = f"/api/runs/{paused['run_id']}"
    with TestClient(create_app(tmp_path, start_worker=False)) as client:
        resumed = client.post(f"{url}/resume", json={"approved": True}).json()
        assert resumed["result"]["kind"] == "task"
        assert resumed["result"]["evidence"] == paused["pending_evidence"]
        assert [step["step"] for step in resumed["trace"]] == ["plan", "retrieve", "approve", "queue"]


def test_retrieval_metrics_distinguish_misses_and_abstention():
    cases = [
        {"query": "diamond cubic", "material": "silicon", "expected": ["silicon-structure"]},
        {"query": "火星天气", "material": None, "expected": []},
    ]
    report = evaluate(cases, "hybrid")
    assert (report["recall_at_3"], report["mrr"], report["abstention_rate"]) == (1, 1, 1)
    assert report["cases"][1]["recall_at_3"] is None


def test_read_only_mcp_tools_over_stdio(tmp_path):
    task_id = TaskStore(tmp_path / "tasks.sqlite").submit("mcp", "iron", "energy", "normal")

    async def run():
        parameters = StdioServerParameters(
            command=sys.executable, args=["-m", "materials_agent.mcp_server"],
            env={**os.environ, "MATERIALS_DATA_DIR": str(tmp_path)},
        )
        async with stdio_client(parameters) as (read, write), ClientSession(read, write) as client:
            await client.initialize()
            tools = (await client.list_tools()).tools
            assert {tool.name for tool in tools} == {"search_knowledge", "get_task_status"}
            assert all(tool.annotations.readOnlyHint for tool in tools)
            knowledge = await client.call_tool("search_knowledge", {"query": "工具超时"})
            task = await client.call_tool("get_task_status", {"task_id": task_id})
            assert not knowledge.isError, knowledge.content
            assert not task.isError, task.content
            assert knowledge.structuredContent["hits"][0]["id"] == "guide-retry"
            assert task.structuredContent["task"]["status"] == "queued"

    asyncio.run(run())
