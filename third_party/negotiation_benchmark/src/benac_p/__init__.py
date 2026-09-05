"""BENAC-P v0: private-preference, public-transcript negotiation games."""

from benac_p.generator import GeneratorConfig, generate_game
from benac_p.observations import PlayerObservation, build_player_observation
from benac_p.oracle import OraclePartnerPolicy, OraclePolicy, RationalOraclePolicy
from benac_p.policies import PlayerPolicy, Proposal, RandomPolicy, ScriptedPolicy
from benac_p.runner import EpisodeResult, GameRunner, run_episode
from benac_p.sampling import generate_sample_bundle, save_sample_bundle
from benac_p.schema import (
    ActionRef,
    GameSpec,
    Goal,
    Offer,
    OfferProposal,
    PassProposal,
    Preference,
    PublicEvent,
    Response,
    ResponseAction,
)
from benac_p.state import GameState, InvalidActionError
from benac_p.solver import (
    PerfectInfoSolver,
    ResponseEvaluation,
    SolverLimitError,
    SolverResult,
    SolverRollout,
    SolverStep,
)
from benac_p.vllm_policy import VLLMPlayerPolicy

__all__ = [
    "ActionRef",
    "EpisodeResult",
    "GameRunner",
    "GameSpec",
    "GeneratorConfig",
    "Goal",
    "GameState",
    "InvalidActionError",
    "OraclePartnerPolicy",
    "OraclePolicy",
    "Offer",
    "OfferProposal",
    "PassProposal",
    "PlayerObservation",
    "PlayerPolicy",
    "PerfectInfoSolver",
    "Preference",
    "Proposal",
    "PublicEvent",
    "RandomPolicy",
    "RationalOraclePolicy",
    "Response",
    "ResponseAction",
    "ResponseEvaluation",
    "ScriptedPolicy",
    "SolverLimitError",
    "SolverResult",
    "SolverRollout",
    "SolverStep",
    "VLLMPlayerPolicy",
    "build_player_observation",
    "generate_game",
    "generate_sample_bundle",
    "run_episode",
    "save_sample_bundle",
]
