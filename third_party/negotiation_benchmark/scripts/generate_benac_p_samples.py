#!/usr/bin/env python3
"""Generate the initial BENAC-P v0 random self-play sample bundle."""

from __future__ import annotations

import argparse

from benac_p.generator import GeneratorConfig
from benac_p.sampling import generate_sample_bundle, save_sample_bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-games", type=int, default=100)
    parser.add_argument("--start-seed", type=int, default=0)
    parser.add_argument("--n-rounds", type=int, default=4)
    parser.add_argument("--output", default="artifacts/benac_p_random_samples.json")
    parser.add_argument("--pass-probability", type=float, default=0.2)
    parser.add_argument("--accept-probability", type=float, default=0.5)
    args = parser.parse_args(argv)
    bundle = generate_sample_bundle(
        n_games=args.n_games,
        start_seed=args.start_seed,
        config=GeneratorConfig(n_rounds=args.n_rounds),
        pass_probability=args.pass_probability,
        accept_probability=args.accept_probability,
    )
    output_path = save_sample_bundle(bundle, args.output)
    summary = bundle["summary"]
    print(
        f"saved {summary['n_games']} games to {output_path}; "
        f"PASS={summary['pass_count']} ACCEPT={summary['accept_count']} "
        f"REJECT={summary['reject_count']}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

