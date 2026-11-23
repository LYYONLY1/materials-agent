"""Small closed-loop benchmark for the local knowledge endpoint."""

import argparse
import asyncio
import json
import math
from time import perf_counter

import httpx

QUERIES = ("硅的晶体结构", "工具超时之后怎么办", "Fe element", "火星天气")


async def measure(port: int, requests: int, concurrency: int, slo_ms: float) -> dict:
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}",
                                 timeout=5, trust_env=False) as client:
        warmup = await client.get("/api/knowledge/search", params={"q": QUERIES[0]})
        warmup.raise_for_status()
        if "hits" not in warmup.json():
            raise ValueError("Expected the local Materials Agent knowledge API")

        async def runner(offset):
            samples = []
            for index in range(offset, requests, concurrency):
                started = perf_counter()
                try:
                    result = await client.get("/api/knowledge/search",
                                              params={"q": QUERIES[index % len(QUERIES)]})
                    success = result.is_success
                except httpx.RequestError:
                    success = False
                samples.append((1000 * (perf_counter() - started), success))
            return samples

        started = perf_counter()
        batches = await asyncio.gather(*(runner(i) for i in range(concurrency)))
        duration = perf_counter() - started
    samples = sorted(sample for batch in batches for sample in batch)
    successful = sum(ok for _, ok in samples)
    return {
        "requests": requests, "concurrency": concurrency, "successes": successful,
        "slo_ms": slo_ms,
        "p50_ms": round(samples[math.ceil(0.5 * requests) - 1][0], 2),
        "p95_ms": round(samples[math.ceil(0.95 * requests) - 1][0], 2),
        "completion_rps": round(successful / duration, 2),
        "slo_goodput_rps": round(sum(ok and ms <= slo_ms for ms, ok in samples) / duration, 2),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--requests", type=int, default=40)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--slo-ms", type=float, default=100)
    args = parser.parse_args()
    if not (1 <= args.port <= 65535 and 1 <= args.concurrency <= min(16, args.requests)
            and args.requests <= 300 and 0 < args.slo_ms < math.inf):
        parser.error("Use 1–300 requests, concurrency 1–16, and a positive SLO")
    report = asyncio.run(measure(args.port, args.requests, args.concurrency, args.slo_ms))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
