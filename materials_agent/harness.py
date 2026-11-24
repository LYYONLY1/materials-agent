from typing import Literal

from .planner import Decision, OfflinePlanner, PlannerFailure

Profile = Literal["standard", "verified"]
MAX_RETRIEVALS = 2
MAX_EXCERPT_CHARS = 450

_RULES = {
    "查一下硅的资料": Decision(action="lookup", material="silicon", calculation=None),
    "硅的晶体结构是什么": Decision(action="lookup", material="silicon", calculation=None),
    "先查铝的资料，再提交几何优化": Decision(
        action="research_calculate", material="aluminum", calculation="relaxation",
    ),
}


def route(planner, message: str):
    rule = _RULES.get(message.strip().rstrip("？?。"))
    if rule is not None:
        return rule, {"mode": "rule", "reason": "known_intent"}
    try:
        decision, metrics = planner.decide(message)
        return decision, {**metrics, "reason": "planner"}
    except PlannerFailure:
        decision, _ = OfflinePlanner().decide(message)
        return Decision(action="lookup", material=decision.material, calculation=None), {
            "mode": "fallback", "reason": "planner_unavailable_read_only",
        }


def excerpts(evidence: list[dict]) -> list[dict]:
    return [{**item, "text": item["text"][:MAX_EXCERPT_CHARS]} for item in evidence]


def review(draft: dict | None, evidence: list[dict]) -> tuple[str, list[str], str]:
    if draft is None:
        return "", [], "no_draft"
    texts = {item["id"]: item["text"] for item in evidence}
    citations = list(dict.fromkeys(draft["citations"]))
    if not citations:
        return "", [], "missing_citation"
    if any(citation not in texts for citation in citations):
        return "", [], "unknown_citation"
    lines = [line.strip() for line in draft["answer"].splitlines() if line.strip()]
    matches = {
        citation for citation in citations
        if any(line in texts[citation] for line in lines)
    }
    if (not lines or set(citations) != matches
            or any(not any(line in texts[citation] for citation in citations) for line in lines)):
        return "", [], "unverified_excerpt"
    return "\n".join(lines), citations, "verified"


def summarize(trace: list[dict]) -> dict:
    calls = [step["metrics"] for step in trace
             if step.get("metrics", {}).get("output_token_limit") is not None]
    return {
        "retrievals": sum(step["step"] == "retrieve" for step in trace),
        "drafts": sum(step["step"] == "draft" and step.get("attempted", False) for step in trace),
        "review": next((step["outcome"] for step in reversed(trace) if step["step"] == "verify"), None),
        "route": next((step["metrics"].get("mode") for step in trace if step["step"] == "plan"), None),
        "model_responses": len(calls),
        "observed_output_token_limits": sum(call["output_token_limit"] for call in calls),
        "reported_tokens": sum(call["total_tokens"] for call in calls) if calls and all(
            "total_tokens" in call for call in calls
        ) else None,
    }
