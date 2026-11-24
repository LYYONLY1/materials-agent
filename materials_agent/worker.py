import asyncio
import hashlib
import json
import logging
import sqlite3
import sys
from contextlib import suppress
from time import perf_counter

from .tasks import Claim, TaskStore

logger = logging.getLogger(__name__)
TOOL_TIMEOUT = 0.35
CALCULATION_TIMEOUT = 25


class CalculationError(RuntimeError):
    pass


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


async def run_ase(claim: Claim) -> dict:
    structure = claim.parameters.get("structure")
    if structure is None and claim.parameters["material"] != "aluminum":
        raise CalculationError("ASE backend supports aluminum only")
    arguments = [sys.executable, "-m", "materials_agent.calculator", claim.parameters["calculation"]]
    if structure is not None:
        arguments.append("--structure")
    process = await asyncio.create_subprocess_exec(
        *arguments, stdin=asyncio.subprocess.PIPE if structure is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        payload = json.dumps(structure).encode() if structure is not None else None
        stdout, stderr = await asyncio.wait_for(process.communicate(payload), timeout=CALCULATION_TIMEOUT)
    finally:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
            await process.wait()
    if process.returncode != 0:
        logger.error("ASE exited with code %s: %s", process.returncode,
                     stderr.decode("utf-8", errors="replace")[-1000:])
        raise CalculationError("ASE calculation failed")
    try:
        return json.loads(stdout)
    except (ValueError, UnicodeError) as error:
        raise CalculationError("ASE returned an invalid result") from error


async def execute(store: TaskStore, claim: Claim) -> None:
    started = perf_counter()
    try:
        if claim.parameters.get("backend") == "ase":
            result = await run_ase(claim)
        else:
            result = await asyncio.wait_for(simulate(claim), timeout=TOOL_TIMEOUT)
    except TimeoutError:
        await asyncio.to_thread(
            store.finish, claim, error="Calculation tool timed out",
            elapsed_ms=round((perf_counter() - started) * 1000, 2),
        )
    except (CalculationError, OSError) as error:
        logger.warning("Calculation failed for task %s: %s", claim.task_id, error)
        await asyncio.to_thread(
            store.finish, claim, error="Local calculation failed", retryable=False,
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
