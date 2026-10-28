"""
Action-space helpers for the RL negotiation wrapper.

The wrapper exposes one subdecision at a time. Partner choice and offer choice
are both represented as masked discrete selections. Offer menus include an
explicit no-deal option that maps to ``reject_deal()`` rather than to a
zero-change accepted offer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import warnings

from core.game_logic import get_all_joint_actions

NO_DEAL_FLAG = 1
DEAL_FLAG = 0


@dataclass(frozen=True)
class OfferMenu:
    """Concrete offer menu plus padded RL-facing tensors."""

    partner_id: int
    candidates: list[Optional[tuple[int, ...]]]
    mask: np.ndarray
    encoded_actions: np.ndarray


def build_partner_mask(state, *, max_players: int, allow_self: bool = False) -> np.ndarray:
    """
    Build a padded legality mask for partner selection.

    ``NegotiationState.legal_negotiation_partners()`` excludes the proposer by
    default. ``allow_self`` remains available for callers that explicitly need
    to model self-negotiation.
    """
    mask = np.zeros(max_players, dtype=np.int8)
    proposer = state.proposer()

    legal_partners = state.legal_negotiation_partners()
    if allow_self and proposer not in legal_partners:
        legal_partners = [*legal_partners, proposer]

    for partner in legal_partners:
        if partner >= max_players:
            raise ValueError(
                f"Partner id {partner} exceeds max_players={max_players}."
            )
        if (not allow_self) and partner == proposer:
            continue
        mask[partner] = 1

    return mask


def build_offer_menu(
    state,
    *,
    partner_id: int,
    max_actions: int,
    max_candidate_offers: int,
    max_changes: int,
    allowed_actions=None,
    forbidden_actions=None,
    include_no_deal: bool = True,
) -> OfferMenu:
    """
    Build a deterministic padded menu of feasible offers for one partner.

    The first candidate is the explicit no-deal action when
    ``include_no_deal=True``. This maps to ``reject_deal()`` in the wrapper.
    """
    raw_candidates = get_all_joint_actions(
        P=state.P,
        p1=state.proposer(),
        p2=partner_id,
        country_idx2num_actions=state.country_idx2num_actions,
        max_changes=max_changes,
        allowed_actions=allowed_actions,
        forbidden_actions=forbidden_actions,
    )

    candidates: list[Optional[tuple[int, ...]]] = []
    if include_no_deal:
        candidates.append(None)

    remaining_slots = max_candidate_offers - len(candidates)
    if remaining_slots <= 0:
        raise ValueError("max_candidate_offers must be at least 1.")

    if len(raw_candidates) > remaining_slots:
        warnings.warn(
            "Offer menu exceeded max_candidate_offers and was truncated. "
            "Consider reducing action branching or increasing the cap."
        )
    candidates.extend(raw_candidates[:remaining_slots])

    encoded_actions = encode_offer_candidates(
        candidates=candidates,
        proposer_id=state.proposer(),
        partner_id=partner_id,
        max_actions=max_actions,
        country_idx2num_actions=state.country_idx2num_actions,
        max_candidate_offers=max_candidate_offers,
    )

    mask = np.zeros(max_candidate_offers, dtype=np.int8)
    mask[: len(candidates)] = 1

    return OfferMenu(
        partner_id=partner_id,
        candidates=candidates,
        mask=mask,
        encoded_actions=encoded_actions,
    )


def encode_offer_candidates(
    *,
    candidates: list[Optional[tuple[int, ...]]],
    proposer_id: int,
    partner_id: int,
    max_actions: int,
    country_idx2num_actions,
    max_candidate_offers: int,
) -> np.ndarray:
    """
    Encode a variable-length menu into a fixed tensor.

    Layout per row:
    - column 0: ``1`` for no-deal, ``0`` for a real offer
    - next ``max_actions`` columns: proposer action bits, padded with 0s
    - final ``max_actions`` columns: partner action bits, padded with 0s
    """
    encoded = np.zeros((max_candidate_offers, 1 + (2 * max_actions)), dtype=np.int8)

    proposer_actions = country_idx2num_actions[proposer_id]
    partner_actions = country_idx2num_actions[partner_id]

    for idx, candidate in enumerate(candidates):
        if candidate is None:
            encoded[idx, 0] = NO_DEAL_FLAG
            continue

        p_bits = candidate[:proposer_actions]
        q_bits = candidate[proposer_actions:]

        if len(p_bits) != proposer_actions or len(q_bits) != partner_actions:
            raise ValueError("Offer candidate does not match proposer/partner lengths.")

        encoded[idx, 0] = DEAL_FLAG
        encoded[idx, 1 : 1 + proposer_actions] = p_bits
        encoded[idx, 1 + max_actions : 1 + max_actions + partner_actions] = q_bits

    return encoded
