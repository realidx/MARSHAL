"""
main.py

Local runner for sweeping main negotiation simulation experiments in paper.

Results are saved as
gzip-compressed pickle files in a local output directory, using the same
folder structure and file format as the cloud runner so that downstream
loading code works identically for both.

Usage:
    python main.py

Results are written to ``./results/<size>_<shift>_games/<uuid>.pkl.gz``.
"""

import gzip
import itertools
import os
import pickle
import uuid

from config.game_configs import ScenarioProfile, create_sat_masks, generate_game_config
from core import one_shot_optim
from core.game_logic import get_payoff_per_country
from core.game_state import NegotiationState
from experiments import runner
from joblib import Parallel, delayed
from methods.negotiation import create_solver, state_key
from tqdm import tqdm

RESULTS_DIR = "./results"
N_TURNS = 5
MAX_CHANGES = 2


def process_single_scenario(params, method_configs):
    """
    Run a single parameter combination locally and save results to disk.

    Generates a game configuration from the given params, optionally runs
    the exact solver (small games) or baseline (large games), then runs all
    heuristic methods. Results are compressed and written to ``RESULTS_DIR``.

    Args:
        params (tuple): ``(structure, bin_frac, k, zipf, seed, shift, size)``
            where:
            - ``structure`` (str): ``"cooperative"`` or ``"adversarial"``.
            - ``bin_frac`` (float): Fraction of binary goals.
            - ``k`` (int): Number of latent factors.
            - ``zipf`` (float): Zipf shape parameter for goal complexity.
            - ``seed`` (int): Random seed.
            - ``shift`` (str): Payoff range shift — ``"negative"``,
              ``"positive"``, or ``"balanced"`` (no shift).
            - ``size`` (str): ``"small"`` (runs exact solver) or ``"large"``
              (runs baseline only).
        method_configs (list[dict]): List of method configuration dicts
            passed to ``runner.run_single_game``.

    Returns:
        str: Filename of the saved result file, or ``"Failed Generation"``
            if game generation raised a ``ValueError``.
    """
    structure, bin_frac, k, zipf, seed, shift, size = params
    local_results = {}

    N_ACTIONS = 1 if size == "small" else 5

    # "balanced" means no shift — pass None to generate_game_config
    shift_arg = shift if shift in ("negative", "positive") else None

    try:
        profile = ScenarioProfile(
            structure_type=structure,
            binary_fraction=bin_frac,
            complexity_zipf_a=zipf,
        )

        country_idx2num_actions = {i: N_ACTIONS for i in range(10)}

        game_config = generate_game_config(
            n_players=10,
            country_idx2num_actions=country_idx2num_actions,
            n_goals=15,
            k_factors=k,
            seed=seed,
            profile=profile,
            shift=shift_arg,
        )
    except ValueError:
        return "Failed Generation"

    game_name = (
        f"10_players_{size}_{shift}_struct_{structure}_bf_{bin_frac}"
        f"_kfactor_{k}_zipf_{zipf}_seed_{seed}"
    )
    current_sat_mask = create_sat_masks(game_config)

    if size == "small":
        game = NegotiationState(
            n_players=game_config["N_PLAYERS"],
            n_actions=game_config["N_ACTIONS"],
            n_turns=N_TURNS,
            G=game_config["G"],
            sat_masks=current_sat_mask,
            country_idx2num_actions=game_config["country_idx2num_actions"],
            seed=seed,
        )
        solver = create_solver(game)
        payoff_vector_true, _, _, P_hist = solver(state_key(game))
        local_results[("True solution", game_name)] = {
            "payoff_vector": payoff_vector_true,
            "P": P_hist[-1],
            "P_hist": P_hist,
        }

    elif size == "large":
        baseline_solution = one_shot_optim.baseline_solution(
            country_idx2num_actions=game_config["country_idx2num_actions"],
            G=game_config["G"],
            sat_masks=current_sat_mask,
        )
        baseline_vector = get_payoff_per_country(
            P=baseline_solution,
            G=game_config["G"],
            sat_masks=current_sat_mask,
        )
        local_results[("Baseline", game_name)] = {
            "payoff_vector": baseline_vector,
            "P": baseline_solution,
        }

    else:
        raise ValueError(
            f"Invalid size category: {size!r}. Expected 'small' or 'large'."
        )

    for method_config in method_configs:
        cfg = method_config.copy()
        cfg["max_changes"] = MAX_CHANGES
        cfg["n_turns"] = N_TURNS
        result, _ = runner.run_single_game(
            game_config,
            current_sat_mask,
            cfg,
            seed,
            collect_data=False,
            collect_for=None,
        )
        local_results[(cfg["name"], game_name)] = result

    save_dir = os.path.join(RESULTS_DIR, f"{size}_{shift}_games")
    os.makedirs(save_dir, exist_ok=True)

    filename = f"{str(uuid.uuid4())}.pkl.gz"
    full_path = os.path.join(save_dir, filename)

    with gzip.open(full_path, "wb") as f:
        pickle.dump({"results": local_results}, f)

    return f"Saved {filename}"


def main():
    """
    Build the parameter sweep and run all tasks locally in parallel.
    """
    print("Starting local sweep...")

    N_SIMS = 50
    C_UCB = 10.0

    method_configs = [
        {
            "name": "upper",
            "how_fallback": "upper",
            "n_sims": N_SIMS,
            "c_ucb": C_UCB,
            "use_prior": False,
            "dp_k": 0,
        },
        {
            "name": "reward",
            "how_fallback": "reward",
            "n_sims": N_SIMS,
            "c_ucb": C_UCB,
            "use_prior": False,
            "dp_k": 0,
        },
        {
            "name": "lower_tighter",
            "how_fallback": "lower_tighter",
            "n_sims": N_SIMS,
            "c_ucb": C_UCB,
            "use_prior": False,
            "dp_k": 0,
        },
    ]

    structure_types = ["adversarial", "cooperative"]
    binary_fractions = [0.0, 0.15, 0.30, 0.50]
    nbr_factors_list = [5, 15]
    complexity_zipf_vals = [1.6, 3.0]
    seeds = range(50)
    shifts = ["negative", "positive", "balanced"]
    sizes = ["small", "large"]

    param_sweep = list(
        itertools.product(
            structure_types,
            binary_fractions,
            nbr_factors_list,
            complexity_zipf_vals,
            seeds,
            shifts,
            sizes,
        )
    )

    print(f"Running {len(param_sweep)} tasks with joblib (n_jobs=-1)...")

    results = Parallel(n_jobs=-1)(
        delayed(process_single_scenario)(p, method_configs) for p in tqdm(param_sweep)
    )

    failed = [r for r in results if r == "Failed Generation"]
    print(
        f"\nDone. {len(param_sweep) - len(failed)}/{len(param_sweep)} tasks succeeded."
    )
    if failed:
        print(f"{len(failed)} tasks failed game generation.")
    print(f"Results saved to: {os.path.abspath(RESULTS_DIR)}")


if __name__ == "__main__":
    main()
