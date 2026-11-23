import asyncio
import os
import sqlite3
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from threading import Lock
from typing import Annotated
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from pydantic import BaseModel, Field

from .planner import ChatCompletionsPlanner, OfflinePlanner
from .tasks import TaskStore
from .worker import run_worker
from .workflow import Parameters, Scenario, build_workflow


class RunRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1200, pattern=r"\S")
    scenario: Scenario = "normal"


def create_app(data_dir: Path, *, start_worker: bool = True, planner=None) -> FastAPI:
    lock = Lock()

    @asynccontextmanager
    async def lifespan(app):
        data_dir.mkdir(parents=True, exist_ok=True)
        store = TaskStore(data_dir / "tasks.sqlite")
        connection = sqlite3.connect(data_dir / "checkpoints.sqlite", check_same_thread=False)
        try:
            app.state.store = store
            app.state.graph = build_workflow(
                planner if planner is not None else configured_planner(),
                SqliteSaver(connection), store.submit,
            )
            worker = asyncio.create_task(run_worker(store)) if start_worker else None
            try:
                yield
            finally:
                if worker is not None:
                    worker.cancel()
                    with suppress(asyncio.CancelledError):
                        await worker
        finally:
            connection.close()

    app = FastAPI(title="Materials Agent", lifespan=lifespan)

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(Path(__file__).with_name("console.html"))

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.post("/api/runs")
    def submit(request: RunRequest, key: Annotated[str | None, Header(
        alias="Idempotency-Key", min_length=1, max_length=128
    )] = None):
        run_id = uuid5(NAMESPACE_URL, f"materials-agent:{key}").hex if key else uuid4().hex
        config = run_config(run_id)
        graph = app.state.graph
        with lock:
            snapshot = graph.get_state(config)
            if snapshot.values.get("run_id"):
                if (snapshot.values["message"], snapshot.values["scenario"]) != (
                    request.message, request.scenario,
                ):
                    raise HTTPException(409, "Idempotency key already used with a different request")
                if snapshot.next and not snapshot.interrupts:
                    invoke(graph, None, config)
            else:
                invoke(graph, {"run_id": run_id, **request.model_dump()}, config)
            return run_view(graph.get_state(config))

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str):
        with lock:
            return run_view(require_run(app.state.graph, run_config(run_id)))

    @app.post("/api/runs/{run_id}/resume")
    def resume(run_id: str, parameters: Parameters):
        config = run_config(run_id)
        graph = app.state.graph
        with lock:
            snapshot = require_run(graph, config)
            if not snapshot.interrupts:
                raise HTTPException(409, "Run is not awaiting input")
            required = set(snapshot.interrupts[0].value["missing"])
            supplied = parameters.model_dump(exclude_none=True)
            if set(supplied) != required:
                raise HTTPException(422, {"required_fields": sorted(required)})
            invoke(graph, Command(resume=supplied), config)
            return run_view(graph.get_state(config))

    @app.get("/api/tasks/{task_id}")
    def get_task(task_id: str):
        task = app.state.store.get(task_id)
        if task is None:
            raise HTTPException(404, "Task not found")
        return task

    return app


def configured_planner():
    key = os.getenv("MATERIALS_MODEL_API_KEY")
    base_url = os.getenv("MATERIALS_MODEL_BASE_URL")
    model = os.getenv("MATERIALS_MODEL_NAME")
    if any((key, base_url, model)):
        if not all((key, base_url, model)):
            raise RuntimeError("Set all three MATERIALS_MODEL_* variables to enable the model")
        return ChatCompletionsPlanner(base_url, key, model)
    return OfflinePlanner()


def run_config(run_id: str) -> dict:
    return {"configurable": {"thread_id": run_id}}


def require_run(graph, config):
    snapshot = graph.get_state(config)
    if not snapshot.values.get("run_id"):
        raise HTTPException(404, "Run not found")
    return snapshot


def invoke(graph, value, config):
    try:
        graph.invoke(value, config)
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as error:
        raise HTTPException(502, "Planner request failed or returned an invalid decision") from error


def run_view(snapshot) -> dict:
    result = snapshot.values.get("result")
    pending = snapshot.interrupts[0].value if snapshot.interrupts else None
    status = "completed" if result else "needs_input" if pending else "pending"
    return {
        "run_id": snapshot.values["run_id"],
        "status": status,
        "missing": pending["missing"] if pending else [],
        "result": result,
        "trace": snapshot.values.get("trace", []),
    }


app = create_app(Path(os.getenv("MATERIALS_DATA_DIR", "var")))
