import asyncio
import hashlib
import logging
import sqlite3
from time import perf_counter

from .tasks import Claim, TaskStore

logger = logging.getLogger(__name__)
TOOL_TIMEOUT = 0.35


async def simulate(claim: Claim) -> dict:
    parameters = claim.parameters
    timeout = parameters["scenario"] == "always_timeout" or (
        parameters["scenario"] == "timeout_once" and claim.attempt == 1
    )
    await asyncio.sleep(2 if timeout else 0.12)
    digest = hashlib.sha256(
        f"{parameters['material']}:{parameters['calculation']}".encode()
    ).hexdigest()
    return {
        "material": parameters["material"],
        "calculation": parameters["calculation"],
        "simulated_score": round(int(digest[:6], 16) / 0xFFFFFF, 4),
        "simulation": True,
    }


async def execute(store: TaskStore, claim: Claim) -> None:
    started = perf_counter()
    try:
        result = await asyncio.wait_for(simulate(claim), timeout=TOOL_TIMEOUT)
    except TimeoutError:
        await asyncio.to_thread(
            store.finish, claim, error="Calculation tool timed out",
            elapsed_ms=round((perf_counter() - started) * 1000, 2),
        )
    else:
        await asyncio.to_thread(
            store.finish, claim, result=result, elapsed_ms=round((perf_counter() - started) * 1000, 2),
        )


async def run_worker(store: TaskStore) -> None:
    while True:
        try:
            claim = await asyncio.to_thread(store.claim)
            if claim is not None:
                await execute(store, claim)
        except sqlite3.Error:
            logger.exception("Worker database operation failed. Polling will continue.")
        await asyncio.sleep(0.08)
