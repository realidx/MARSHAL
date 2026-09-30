"""Collect repeated Tic-Tac-Toe decisions from a local OpenAI-compatible server."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen


def read_jsonl(path):
    with path.open() as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seed_for(board, replica, seed):
    payload = f"{seed}:{board}:{replica}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:4], "big")


def one_request(args, job):
    request = dict(model=args.model, messages=job["messages"], seed=job["seed"],
                   temperature=args.temperature, top_p=args.top_p, top_k=args.top_k,
                   max_tokens=args.max_tokens, stop=["</answer>"],
                   include_stop_str_in_output=True)
    http = Request(args.base_url.rstrip("/") + "/chat/completions",
                   data=json.dumps(request).encode(),
                   headers={"Content-Type": "application/json"})
    started = time.monotonic()
    try:
        with urlopen(http, timeout=args.timeout) as response:
            raw = json.load(response)
        choice = raw["choices"][0]
        message = choice["message"]
        content = message.get("content")
        if not isinstance(content, str):
            raise ValueError("Server returned no text content")
        return dict(index=job["index"], board=job["board"], replica=job["replica"],
                    seed=job["seed"], status="ok", response=content,
                    finish_reason=choice.get("finish_reason"), usage=raw.get("usage"),
                    elapsed_seconds=round(time.monotonic() - started, 3))
    except Exception as exc:
        return dict(index=job["index"], board=job["board"], replica=job["replica"],
                    seed=job["seed"], status="failed", error=f"{type(exc).__name__}: {exc}",
                    elapsed_seconds=round(time.monotonic() - started, 3))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--checkpoint-hash", required=True)
    parser.add_argument("--replicas", type=int, default=16)
    parser.add_argument("--limit", type=int, default=0, help="0 means the full panel")
    parser.add_argument("--concurrency", type=int, default=16)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--top-p", type=float, default=0.8)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--max-tokens", type=int, default=600)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    if not 1 <= args.replicas <= 128 or not 1 <= args.concurrency <= 32:
        parser.error("replicas must be 1–128 and concurrency 1–32")
    if args.limit < 0 or not 0 <= args.temperature <= 2 or not 0 < args.top_p <= 1:
        parser.error("Invalid limit or sampling settings")
    if args.output.exists():
        raise ValueError(f"Use a new output directory: {args.output}")
    panel = list(read_jsonl(args.panel))
    if args.limit:
        panel = panel[:args.limit]
    jobs = [dict(index=index, board=row["board"], replica=replica,
                 seed=seed_for(row["board"], replica, args.seed), messages=row["messages"])
            for index, (row, replica) in enumerate((row, replica) for row in panel
                                                   for replica in range(args.replicas))]
    args.output.mkdir(parents=True)
    with (args.output / "requests.jsonl").open("w") as handle:
        for job in jobs:
            handle.write(json.dumps(job) + "\n")
    protocol = dict(panel_sha256=sha(args.panel), checkpoint_hash=args.checkpoint_hash,
                    model=args.model, replicas=args.replicas, limit=args.limit,
                    concurrency=args.concurrency, seed=args.seed,
                    temperature=args.temperature, top_p=args.top_p, top_k=args.top_k,
                    max_tokens=args.max_tokens, stop="</answer>",
                    include_stop_str_in_output=True, jobs=len(jobs),
                    request_sha256=sha(args.output / "requests.jsonl"))
    (args.output / "protocol.json").write_text(json.dumps(protocol, indent=2) + "\n")
    results = []
    with (args.output / "calls.jsonl").open("w") as handle:
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures = [pool.submit(one_request, args, job) for job in jobs]
            for future in as_completed(futures):
                row = future.result()
                results.append(row)
                handle.write(json.dumps(row) + "\n")
                handle.flush()
                if len(results) % 128 == 0 or len(results) == len(jobs):
                    print(f"completed {len(results)}/{len(jobs)}", flush=True)
    results.sort(key=lambda row: row["index"])
    with (args.output / "samples.jsonl").open("w") as handle:
        for row in results:
            if row["status"] == "ok":
                handle.write(json.dumps(dict(board=row["board"], response=row["response"],
                                             finish_reason=row["finish_reason"])) + "\n")
    summary = dict(**protocol, completed=len(results),
                   statuses=dict(Counter(row["status"] for row in results)),
                   finish_reasons=dict(Counter(row.get("finish_reason") for row in results if row["status"] == "ok")),
                   samples_sha256=sha(args.output / "samples.jsonl"),
                   complete=len(results) == len(jobs) and all(row["status"] == "ok" for row in results))
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    if not summary["complete"]:
        raise RuntimeError("Some requests failed; inspect calls.jsonl")
    (args.output / "COMPLETE.json").write_text(json.dumps(dict(jobs=len(jobs),
        checkpoint_hash=args.checkpoint_hash, samples_sha256=summary["samples_sha256"])) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
