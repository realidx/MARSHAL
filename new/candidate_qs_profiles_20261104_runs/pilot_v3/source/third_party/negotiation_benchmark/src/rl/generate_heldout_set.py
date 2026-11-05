"""
Generate and save the default held-out evaluation set.
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rl.heldout import generate_heldout_games, save_heldout_games


def main():
    output_path = Path("games") / "heldout_eval_set.pkl"
    bundle = generate_heldout_games()
    save_heldout_games(bundle, output_path)
    print(f"Saved held-out set with {bundle['metadata']['num_games']} games to {output_path.resolve()}")


if __name__ == "__main__":
    main()
