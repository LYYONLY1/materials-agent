"""Read-only MCP tools over stdio for a local Materials Agent installation."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from .planner import Material
from .retrieval import configured_index
from .tasks import TaskStore

server = FastMCP("Materials Agent")
knowledge_index = lru_cache(maxsize=1)(configured_index)


class SearchOutput(BaseModel):
    hits: list[dict]


class TaskOutput(BaseModel):
    task: dict | None


@server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
def search_knowledge(query: Annotated[str, Field(min_length=1, max_length=300)],
                     material: Material | None = None) -> SearchOutput:
    """Search the local materials knowledge base and return ranked evidence."""
    return SearchOutput(hits=knowledge_index().search(query, material))


@server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
def get_task_status(task_id: Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]) -> TaskOutput:
    """Read an existing task's state and event history using its task ID."""
    path = Path(os.getenv("MATERIALS_DATA_DIR", "var")) / "tasks.sqlite"
    task = TaskStore(path, readonly=True).get(task_id) if path.is_file() else None
    return TaskOutput(task=task)


if __name__ == "__main__":
    server.run(transport="stdio")
