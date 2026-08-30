"""Structured Item Coalition Game with collaboration and rerouting support."""

from .config import ItemGameConfig
from .env import ItemGameEnv
from .game import BaseItemGame
from .self_play import HuggingFaceSelfPlayPolicy, SelfPlayEpisodeResult, SelfPlayItemGame, SelfPlayRunner
from .synchronous_self_play import (
    HuggingFaceSynchronousSelfPlayPolicy,
    SelfPlayPolicyOutput,
    SynchronousEpisodeResult,
    SynchronousItemGame,
    SynchronousSelfPlayRunner,
    VLLMSynchronousSelfPlayPolicy,
    VLLMSelfPlayPolicy,
)
from .generator import (
    GENERATOR_NAMES,
    SUBTYPES,
    ItemGameInstance,
    MixedIncentiveGenerator,
    PureCollaborationGenerator,
    ResourceConflictGenerator,
    generate_instance,
    validate_instance,
)

__all__ = [
    "BaseItemGame",
    "GENERATOR_NAMES",
    "ItemGameConfig",
    "ItemGameEnv",
    "HuggingFaceSelfPlayPolicy",
    "SelfPlayEpisodeResult",
    "SelfPlayItemGame",
    "SelfPlayRunner",
    "HuggingFaceSynchronousSelfPlayPolicy",
    "SelfPlayPolicyOutput",
    "SynchronousEpisodeResult",
    "SynchronousItemGame",
    "SynchronousSelfPlayRunner",
    "VLLMSynchronousSelfPlayPolicy",
    "VLLMSelfPlayPolicy",
    "ItemGameInstance",
    "MixedIncentiveGenerator",
    "PureCollaborationGenerator",
    "ResourceConflictGenerator",
    "SUBTYPES",
    "generate_instance",
    "validate_instance",
]
