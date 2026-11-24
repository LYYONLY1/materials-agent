from collections.abc import Callable
from time import perf_counter
from typing import Literal, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel, StrictBool

from .catalog import search_reference
from .harness import MAX_RETRIEVALS, Profile, excerpts, review, route
from .planner import Calculation, Decision, Material, OfflinePlanner, Planner, PlannerFailure
from .retrieval import INDEX, KnowledgeIndex

Scenario = Literal["normal", "timeout_once", "always_timeout"]
Backend = Literal["mock", "ase"]
ABSTENTION = "现有资料不足以回答这个问题。可以尝试查询硅、铝、铁或工作台的计算和重试规则。"


class Parameters(BaseModel):
    material: Material | None = None
    calculation: Calculation | None = None
    approved: StrictBool | None = None


class WorkflowState(TypedDict, total=False):
    run_id: str
    message: str
    scenario: Scenario
    backend: Backend
    profile: Profile
    require_approval: bool
    approved: bool
    evidence: list[dict]
    used_evidence: list[str]
    draft: dict | None
    decision: dict
    trace: list[dict]
    result: dict


def build_workflow(
    planner: Planner,
    checkpoints: BaseCheckpointSaver,
    submit: Callable[[str, str, str, Scenario, Backend], str],
    knowledge: KnowledgeIndex = INDEX,
):
    def plan(state: WorkflowState) -> dict:
        started = perf_counter()
        decision, metrics = (
            route(planner, state["message"]) if state.get("profile") == "verified"
            else planner.decide(state["message"])
        )
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
        attempt = 1 + sum(item["step"] == "retrieve" for item in state["trace"])
        material = state["decision"]["material"]
        query = state["message"]
        if state["decision"]["action"] == "research_calculate":
            calculation = {"energy": "能量计算", "relaxation": "几何优化"}[
                state["decision"]["calculation"]
            ]
            query = f"{material} 元素 晶体结构 {calculation}"
        mode = "hybrid" if attempt == 1 else "bm25"
        evidence = knowledge.search(query, material, mode=mode)
        if attempt > 1:
            used = set(state.get("used_evidence", []))
            evidence = [item for item in evidence if item["id"] not in used]
        return {
            "evidence": evidence,
            "trace": [*state["trace"], {
                "step": "retrieve", "material": material, "elapsed_ms": elapsed(started),
                "evidence_ids": [item["id"] for item in evidence],
                "attempt": attempt, "strategy": mode,
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
        answer = ABSTENTION
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

    def draft(state: WorkflowState) -> dict:
        started = perf_counter()
        evidence = excerpts(state["evidence"])
        candidate = None
        metrics = {"mode": "skipped"}
        if evidence:
            source = OfflinePlanner() if state["trace"][0]["metrics"]["mode"] == "fallback" else planner
            answer = getattr(source, "select_excerpts", source.answer)
            try:
                response, metrics = answer(state["message"], evidence)
                candidate = response.model_dump()
            except PlannerFailure:
                metrics = {"mode": "error", "reason": "answer_provider_error"}
        return {
            "draft": candidate,
            "used_evidence": [*state.get("used_evidence", []), *(item["id"] for item in evidence)],
            "trace": [*state["trace"], {
                "step": "draft", "elapsed_ms": elapsed(started), "attempted": bool(evidence),
                "context_chars": sum(len(item["text"]) for item in evidence), "metrics": metrics,
            }],
        }

    def verify(state: WorkflowState) -> dict:
        started = perf_counter()
        evidence = excerpts(state["evidence"])
        answer, citations, outcome = review(state.get("draft"), evidence)
        trace = [*state["trace"], {
            "step": "verify", "outcome": outcome, "citations": citations, "elapsed_ms": elapsed(started),
        }]
        update = {"trace": trace}
        if outcome == "verified" or sum(item["step"] == "retrieve" for item in trace) >= MAX_RETRIEVALS:
            update["result"] = {
                "kind": "reference", "answer": answer or ABSTENTION, "citations": citations,
                "evidence": evidence, "abstained": not citations,
                "reference": search_reference(state["decision"]["material"]),
            }
        return update

    def approve(state: WorkflowState) -> dict:
        supplied = Parameters.model_validate(interrupt({
            "missing": ["approved"], "parameters": {
                **state["decision"], "backend": state.get("backend", "mock"),
            },
            "evidence": state.get("evidence", []),
        }))
        return {
            "approved": supplied.approved,
            "trace": [*state["trace"], {"step": "approve", "approved": supplied.approved}],
        }

    def decline(state: WorkflowState) -> dict:
        return {"result": {"kind": "declined"}}

    def unsupported(state: WorkflowState) -> dict:
        return {"result": {"kind": "unsupported", "reason": "ASE backend supports aluminum only"}}

    def queue(state: WorkflowState) -> dict:
        started = perf_counter()
        decision = Decision.model_validate(state["decision"])
        assert decision.material is not None and decision.calculation is not None
        task_id = submit(
            state["run_id"], decision.material, decision.calculation, state["scenario"],
            state.get("backend", "mock"),
        )
        return {
            "result": {"kind": "task", "task_id": task_id, "evidence": state.get("evidence", [])},
            "trace": [*state["trace"], {
                "step": "queue", "task_id": task_id, "elapsed_ms": elapsed(started),
            }],
        }

    def after_clarify(state: WorkflowState) -> str:
        action = state["decision"]["action"]
        native = state.get("backend") == "ase"
        if action != "lookup" and native and state["decision"]["material"] != "aluminum":
            return "unsupported"
        if action in {"lookup", "research_calculate"}:
            return "retrieve"
        return "approve" if native or state.get("require_approval") or state.get("profile") == "verified" else "queue"

    def after_retrieve(state: WorkflowState) -> str:
        if state["decision"]["action"] != "lookup":
            return "approve"
        return "draft" if state.get("profile") == "verified" else "lookup"

    graph = StateGraph(WorkflowState)
    graph.add_node("plan", plan)
    graph.add_node("clarify", clarify)
    graph.add_node("retrieve", retrieve)
    graph.add_node("lookup", lookup)
    graph.add_node("draft", draft)
    graph.add_node("verify", verify)
    graph.add_node("approve", approve)
    graph.add_node("decline", decline)
    graph.add_node("unsupported", unsupported)
    graph.add_node("queue", queue)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "clarify")
    graph.add_conditional_edges(
        "clarify", after_clarify, ["retrieve", "approve", "queue", "unsupported"],
    )
    graph.add_conditional_edges("retrieve", after_retrieve, ["lookup", "draft", "approve"])
    graph.add_edge("draft", "verify")
    graph.add_conditional_edges(
        "verify", lambda state: END if "result" in state else "retrieve", [END, "retrieve"],
    )
    graph.add_conditional_edges(
        "approve", lambda state: "queue" if state["approved"] else "decline", ["queue", "decline"],
    )
    graph.add_edge("lookup", END)
    graph.add_edge("queue", END)
    graph.add_edge("decline", END)
    graph.add_edge("unsupported", END)
    return graph.compile(checkpointer=checkpoints)


def elapsed(started: float) -> float:
    return round((perf_counter() - started) * 1000, 2)
