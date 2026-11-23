import re
from typing import Literal, Protocol

import httpx
from pydantic import BaseModel, Field

from .catalog import REFERENCES

Material = Literal["silicon", "aluminum", "iron"]
Calculation = Literal["relaxation", "energy"]


class Decision(BaseModel):
    action: Literal["lookup", "calculate"]
    material: Material | None = Field(description="Material named by the user, or null")
    calculation: Calculation | None = Field(description="Calculation requested by the user, or null")


class Planner(Protocol):
    def decide(self, message: str) -> Decision: ...
    def answer(self, message: str, reference: dict) -> str: ...


class PlannerFailure(RuntimeError):
    pass


class OfflinePlanner:
    """Deterministic fixture for local runs and regression tests."""

    def decide(self, message: str) -> Decision:
        query = message.casefold()
        material = next(
            (
                reference.material
                for reference in REFERENCES
                if any(
                    alias in query if not alias.isascii()
                    else re.search(rf"\b{re.escape(alias)}\b", query)
                    for alias in reference.aliases
                )
            ),
            None,
        )
        calculation = None
        if any(term in query for term in ("几何优化", "弛豫", "relaxation", "relax")):
            calculation = "relaxation"
        elif any(term in query for term in ("能量", "energy")):
            calculation = "energy"
        calculate = calculation is not None or any(
            term in query for term in ("计算", "提交", "模拟", "compute", "calculate", "simulate")
        )
        return Decision(
            action="calculate" if calculate else "lookup",
            material=material,
            calculation=calculation,
        )

    def answer(self, message: str, reference: dict) -> str:
        return reference["summary"]


class ChatCompletionsPlanner:
    """Optional adapter for a user-configured Chat Completions endpoint."""

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def decide(self, message: str) -> Decision:
        try:
            reply = self.complete(
                messages=[
                    {"role": "system", "content": (
                        "Route this materials lab request. Use lookup for questions about "
                        "a material and calculate only when the user requests a simulation. "
                        "Identify silicon, aluminum, or iron and relaxation or energy if "
                        "stated. Return null for missing or unknown values. Never guess."
                    )},
                    {"role": "user", "content": message},
                ],
                tools=[{"type": "function", "function": {
                    "name": "plan_materials_request",
                    "description": "Record the routing decision and extracted parameters.",
                    "parameters": Decision.model_json_schema(),
                }}],
                tool_choice={"type": "function", "function": {"name": "plan_materials_request"}},
            )
            calls = reply["tool_calls"]
            if len(calls) != 1 or calls[0]["function"]["name"] != "plan_materials_request":
                raise ValueError("Unexpected tool call")
            return Decision.model_validate_json(calls[0]["function"]["arguments"])
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise PlannerFailure("Invalid response from model") from error

    def answer(self, message: str, reference: dict) -> str:
        reply = self.complete(messages=[
            {"role": "system", "content": (
                "Answer briefly in the language of the question using only the provided "
                "reference excerpt. If the excerpt is insufficient, say so. "
                "Never treat simulated scores as physical results."
            )},
            {"role": "user", "content": f"Question: {message}\nReference: {reference['summary']}"},
        ])
        content = reply.get("content")
        if not isinstance(content, str) or not content.strip():
            raise PlannerFailure("Model returned an empty answer")
        return content.strip()

    def complete(self, **body) -> dict:
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, **body},
                timeout=12,
            )
            response.raise_for_status()
            message = response.json()["choices"][0]["message"]
            if not isinstance(message, dict):
                raise TypeError("Expected a message object")
            return message
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
            raise PlannerFailure("Model request failed") from error
