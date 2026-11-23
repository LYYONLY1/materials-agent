import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from materials_agent.api import create_app
from materials_agent.planner import ChatCompletionsPlanner
from materials_agent.tasks import TaskStore
from materials_agent.worker import execute


def submit(client, message, scenario="normal", key=None):
    response = client.post(
        "/api/runs",
        json={"message": message, "scenario": scenario},
        headers={"Idempotency-Key": key or uuid4().hex},
    )
    assert response.status_code == 200, response.text
    return response.json()


def completed_task(client, task_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(f"/api/tasks/{task_id}")
        assert response.status_code == 200, response.text
        task = response.json()
        if task["status"] in {"succeeded", "failed"}:
            return task
        time.sleep(0.04)
    raise AssertionError("Task did not reach a terminal state")


def test_reference_has_source_and_correct_tool(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        run = submit(client, "查一下硅的资料")
        assert run["result"]["reference"]["url"].endswith("/Silicon")
        assert "硅" in run["result"]["answer"]
        assert run["result"]["citations"] == ["silicon-identity"]
        assert [step["step"] for step in run["trace"]] == ["plan", "retrieve", "lookup"]


def test_clarification_survives_app_restart(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        run = submit(client, "提交能量计算")
        assert run["status"] == "needs_input"
        assert run["missing"] == ["material"]
    with TestClient(create_app(tmp_path)) as client:
        run_url = f"/api/runs/{run['run_id']}"
        assert client.get(run_url).json()["missing"] == ["material"]
        assert client.post(f"{run_url}/resume", json={"material": "copper"}).status_code == 422
        assert client.post(f"{run_url}/resume", json={"calculation": "energy"}).status_code == 422
        resumed = client.post(f"{run_url}/resume", json={"material": "iron"}).json()
        assert [step["step"] for step in resumed["trace"]] == ["plan", "clarify", "queue"]
        task = completed_task(client, resumed["result"]["task_id"])
        assert task["result"]["material"] == "iron"
        assert client.post(f"{run_url}/resume", json={"material": "iron"}).status_code == 409


def test_duplicate_request_and_key_conflict(tmp_path):
    message = "calculate silicon energy"
    with TestClient(create_app(tmp_path)) as client:
        with ThreadPoolExecutor(max_workers=4) as pool:
            runs = list(pool.map(lambda _: submit(client, message, key="same-key"), range(4)))
        run = runs[0]
        task_id = run["result"]["task_id"]
        assert {run["result"]["task_id"] for run in runs} == {task_id}
        conflict = client.post("/api/runs", json={"message": "look up silicon"},
                               headers={"Idempotency-Key": "same-key"})
        assert conflict.status_code == 409
        task = completed_task(client, task_id)
        assert task["attempts"] == 1
        assert [event["event"] for event in task["events"]] == ["queued", "started", "succeeded"]
    with TestClient(create_app(tmp_path)) as client:
        assert submit(client, message, key="same-key")["result"]["task_id"] == task_id


def test_timeout_retries_once_and_succeeds(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        run = submit(client, "提交铝的能量计算", "timeout_once")
        task = completed_task(client, run["result"]["task_id"])
        assert task["status"] == "succeeded"
        assert task["attempts"] == 2
        assert [event["event"] for event in task["events"]] == [
            "queued", "started", "retry_scheduled", "started", "succeeded",
        ]
        assert task["events"][2]["details"]["error"] == "Calculation tool timed out"
        assert task["result"]["simulation"] is True


def test_permanent_timeout_stops_at_retry_budget(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        run = submit(client, "模拟硅的几何优化", "always_timeout")
        task = completed_task(client, run["result"]["task_id"])
        assert task["status"] == "failed"
        assert task["attempts"] == 2
        assert task["result"] is None
        assert task["events"][-1]["event"] == "failed"


def test_worker_restart_reclaims_lease_and_blocks_stale_result(tmp_path):
    path = tmp_path / "tasks.sqlite"
    previous = TaskStore(path)
    task_id = previous.submit("fixed-run", "silicon", "energy", "normal")
    lost_claim = previous.claim(now=100, lease_seconds=3)
    restarted = TaskStore(path)
    assert restarted.submit("fixed-run", "silicon", "energy", "normal") == task_id
    assert restarted.claim(now=102) is None
    retry = restarted.claim(now=104)
    assert retry.task_id == lost_claim.task_id == task_id
    assert not previous.finish(lost_claim, result={"stale": True})
    asyncio.run(execute(restarted, retry))
    task = restarted.get(task_id)
    assert task["attempts"] == 2
    assert task["status"] == "succeeded"
    assert task["events"][2]["details"]["error"] == "Worker lease expired"
    assert sum(event["event"] == "succeeded" for event in task["events"]) == 1


def test_replay_after_task_commit_does_not_enqueue_twice(tmp_path, monkeypatch):
    original = TaskStore.submit
    stored_ids = []

    def interrupted_submit(store, *args):
        task_id = original(store, *args)
        stored_ids.append(task_id)
        raise RuntimeError("Simulated interruption before graph checkpoint")

    request = {"message": "calculate silicon energy"}
    headers = {"Idempotency-Key": "graph-replay"}
    with monkeypatch.context() as patch:
        patch.setattr(TaskStore, "submit", interrupted_submit)
        with TestClient(create_app(tmp_path, start_worker=False),
                        raise_server_exceptions=False) as client:
            assert client.post("/api/runs", json=request, headers=headers).status_code == 500
    with TestClient(create_app(tmp_path)) as client:
        run = client.post("/api/runs", json=request, headers=headers).json()
        assert [run["result"]["task_id"]] == stored_ids
        task = completed_task(client, stored_ids[0])
        assert task["attempts"] == 1
        assert [event["event"] for event in task["events"]] == ["queued", "started", "succeeded"]


def test_model_adapter_uses_structured_tool_and_cited_context(tmp_path, monkeypatch):
    requests = []

    def fake_post(url, *, headers, json, timeout):
        requests.append(json)
        if json["tool_choice"]["function"]["name"] == "plan_materials_request":
            reply = {"tool_calls": [{"function": {
                "name": "plan_materials_request",
                "arguments": '{"action":"lookup","material":"silicon","calculation":null}',
            }}]}
        else:
            assert "硅是元素 Si" in json["messages"][-1]["content"]
            reply = {"tool_calls": [{"function": {
                "name": "report_grounded_answer",
                "arguments": '{"answer":"硅是元素 Si。","citations":["silicon-identity"]}',
            }}]}
        return httpx.Response(200, request=httpx.Request("POST", url),
                              json={"choices": [{"message": reply}],
                                    "usage": {"prompt_tokens": 10, "completion_tokens": 6,
                                              "total_tokens": 16}})

    monkeypatch.setattr(httpx, "post", fake_post)
    planner = ChatCompletionsPlanner("https://example.com/v1", "test-only", "local-test")
    with TestClient(create_app(tmp_path, planner=planner)) as client:
        run = submit(client, "硅是什么")
        assert run["result"]["answer"] == "硅是元素 Si。"
        assert run["result"]["reference"]["url"].endswith("/Silicon")
        assert run["trace"][-1]["metrics"]["total_tokens"] == 16
    assert len(requests) == 2
    assert [request["max_tokens"] for request in requests] == [256, 512]
