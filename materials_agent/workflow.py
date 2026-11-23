from collections.abc import Callable
from time import perf_counter
from typing import Literal, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel, StrictBool

from .catalog import search_reference
from .planner import Calculation, Decision, Material, Planner
from .retrieval import INDEX, KnowledgeIndex

Scenario = Literal["normal", "timeout_once", "always_timeout"]


class Parameters(BaseModel):
    material: Material | None = None
    calculation: Calculation | None = None
    approved: StrictBool | None = None


class WorkflowState(TypedDict, total=False):
    run_id: str
    message: str
    scenario: Scenario
    require_approval: bool
    approved: bool
    evidence: list[dict]
    decision: dict
    trace: list[dict]
    result: dict


def build_workflow(
    planner: Planner,
    checkpoints: BaseCheckpointSaver,
    submit: Callable[[str, str, str, Scenario], str],
    knowledge: KnowledgeIndex = INDEX,
):
    def plan(state: WorkflowState) -> dict:
        started = perf_counter()
        decision, metrics = planner.decide(state["message"])
        return {
            "decision": decision.model_dump(),
            "trace": [{
                "step": "plan", "elapsed_ms": elapsed(started),
                "action": decision.action, "parameters": decision.model_dump(exclude={"action"}),
                "metrics": metrics,
            }],
        }

    def clarify(state: WorkflowState) -> dict:
        decision = Decision.model_validate(state["decision"])
        missing = []
        if decision.action != "lookup" and decision.material is None:
            missing.append("material")
        if decision.action != "lookup" and decision.calculation is None:
            missing.append("calculation")
        if not missing:
            return {}
        supplied = Parameters.model_validate(interrupt({"missing": missing}))
        values = supplied.model_dump(exclude_none=True)
        return {
            "decision": {**state["decision"], **values},
            "trace": [*state["trace"], {"step": "clarify", "parameters": values}],
        }

    def retrieve(state: WorkflowState) -> dict:
        started = perf_counter()
        material = state["decision"]["material"]
        query = state["message"]
        if state["decision"]["action"] == "research_calculate":
            calculation = {"energy": "能量计算", "relaxation": "几何优化"}[
                state["decision"]["calculation"]
            ]
            query = f"{material} 元素 晶体结构 {calculation}"
        evidence = knowledge.search(query, material)
        return {
            "evidence": evidence,
            "trace": [*state["trace"], {
                "step": "retrieve", "material": material, "elapsed_ms": elapsed(started),
                "evidence_ids": [item["id"] for item in evidence],
            }],
        }

    def lookup(state: WorkflowState) -> dict:
        started = perf_counter()
        material = state["decision"]["material"]
        evidence = state.get("evidence")
        if evidence is None:
            evidence = knowledge.search(state["message"], material)
        metrics = {"mode": "skipped"}
        citations = []
        answer = "现有资料不足以回答这个问题。可以尝试查询硅、铝、铁或工作台的计算和重试规则。"
        if evidence:
            response, metrics = planner.answer(state["message"], evidence)
            available = {item["id"] for item in evidence}
            if response.citations and set(response.citations) <= available:
                citations = list(dict.fromkeys(response.citations))
                answer = response.answer
        return {
            "result": {
                "kind": "reference", "reference": search_reference(material),
                "answer": answer, "citations": citations, "evidence": evidence,
                "abstained": not citations,
            },
            "trace": [*state["trace"], {
                "step": "lookup", "material": material, "elapsed_ms": elapsed(started),
                "metrics": metrics, "citations": citations,
            }],
        }

    def approve(state: WorkflowState) -> dict:
        supplied = Parameters.model_validate(interrupt({
            "missing": ["approved"], "parameters": state["decision"],
            "evidence": state.get("evidence", []),
        }))
        return {
            "approved": supplied.approved,
            "trace": [*state["trace"], {"step": "approve", "approved": supplied.approved}],
        }

    def decline(state: WorkflowState) -> dict:
        return {"result": {"kind": "declined"}}

    def queue(state: WorkflowState) -> dict:
        started = perf_counter()
        decision = Decision.model_validate(state["decision"])
        assert decision.material is not None and decision.calculation is not None
        task_id = submit(state["run_id"], decision.material, decision.calculation, state["scenario"])
        return {
            "result": {"kind": "task", "task_id": task_id, "evidence": state.get("evidence", [])},
            "trace": [*state["trace"], {
                "step": "queue", "task_id": task_id, "elapsed_ms": elapsed(started),
            }],
        }

    graph = StateGraph(WorkflowState)
    graph.add_node("plan", plan)
    graph.add_node("clarify", clarify)
    graph.add_node("retrieve", retrieve)
    graph.add_node("lookup", lookup)
    graph.add_node("approve", approve)
    graph.add_node("decline", decline)
    graph.add_node("queue", queue)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "clarify")
    graph.add_conditional_edges(
        "clarify", lambda state: (
            "retrieve" if state["decision"]["action"] != "calculate"
            else "approve" if state.get("require_approval") else "queue"
        ),
        ["retrieve", "approve", "queue"],
    )
    graph.add_conditional_edges(
        "retrieve", lambda state: (
            "lookup" if state["decision"]["action"] == "lookup" else "approve"
        ), ["lookup", "approve"],
    )
    graph.add_conditional_edges(
        "approve", lambda state: "queue" if state["approved"] else "decline", ["queue", "decline"],
    )
    graph.add_edge("lookup", END)
    graph.add_edge("queue", END)
    graph.add_edge("decline", END)
    return graph.compile(checkpointer=checkpoints)


def elapsed(started: float) -> float:
    return round((perf_counter() - started) * 1000, 2)
