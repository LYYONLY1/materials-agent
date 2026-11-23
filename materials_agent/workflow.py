from collections.abc import Callable
from time import perf_counter
from typing import Literal, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel

from .catalog import search_reference
from .planner import Calculation, Decision, Material, Planner

Scenario = Literal["normal", "timeout_once", "always_timeout"]


class Parameters(BaseModel):
    material: Material | None = None
    calculation: Calculation | None = None


class WorkflowState(TypedDict, total=False):
    run_id: str
    message: str
    scenario: Scenario
    decision: dict
    trace: list[dict]
    result: dict


def build_workflow(
    planner: Planner,
    checkpoints: BaseCheckpointSaver,
    submit: Callable[[str, str, str, Scenario], str],
):
    def plan(state: WorkflowState) -> dict:
        started = perf_counter()
        decision = planner.decide(state["message"])
        return {
            "decision": decision.model_dump(),
            "trace": [{
                "step": "plan", "elapsed_ms": elapsed(started),
                "action": decision.action, "parameters": decision.model_dump(exclude={"action"}),
            }],
        }

    def clarify(state: WorkflowState) -> dict:
        decision = Decision.model_validate(state["decision"])
        missing = []
        if decision.material is None:
            missing.append("material")
        if decision.action == "calculate" and decision.calculation is None:
            missing.append("calculation")
        if not missing:
            return {}
        supplied = Parameters.model_validate(interrupt({"missing": missing}))
        values = supplied.model_dump(exclude_none=True)
        return {
            "decision": {**state["decision"], **values},
            "trace": [*state["trace"], {"step": "clarify", "parameters": values}],
        }

    def lookup(state: WorkflowState) -> dict:
        started = perf_counter()
        material = state["decision"]["material"]
        return {
            "result": {"kind": "reference", "reference": search_reference(material)},
            "trace": [*state["trace"], {
                "step": "lookup", "material": material, "elapsed_ms": elapsed(started),
            }],
        }

    def queue(state: WorkflowState) -> dict:
        started = perf_counter()
        decision = Decision.model_validate(state["decision"])
        assert decision.material is not None and decision.calculation is not None
        task_id = submit(state["run_id"], decision.material, decision.calculation, state["scenario"])
        return {
            "result": {"kind": "task", "task_id": task_id},
            "trace": [*state["trace"], {
                "step": "queue", "task_id": task_id, "elapsed_ms": elapsed(started),
            }],
        }

    graph = StateGraph(WorkflowState)
    graph.add_node("plan", plan)
    graph.add_node("clarify", clarify)
    graph.add_node("lookup", lookup)
    graph.add_node("queue", queue)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "clarify")
    graph.add_conditional_edges(
        "clarify", lambda state: state["decision"]["action"],
        {"lookup": "lookup", "calculate": "queue"},
    )
    graph.add_edge("lookup", END)
    graph.add_edge("queue", END)
    return graph.compile(checkpointer=checkpoints)


def elapsed(started: float) -> float:
    return round((perf_counter() - started) * 1000, 2)
