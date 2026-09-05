"""
baselines.py

LLM-based negotiation baseline using an OpenAI-compatible text client.

Provides a decision-making agent that uses an LLM (via OpenAI's chat
completions API) to select a negotiation partner and propose a joint action
on each turn. The game state is serialised into a structured JSON prompt
split into a static (cacheable) context and a dynamic per-turn state, which
reduces token costs on repeated calls.

Includes retry logic with exponential backoff and validation of the LLM's
output against game constraints (action budget, vector lengths, valid partner
indices).
"""

import json
import numpy as np
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

client = None


def _get_openai_client():
    """Create the OpenAI client only when the OpenAI backend is requested."""
    global client
    if client is None:
        from openai import OpenAI

        client = OpenAI()
    return client


@retry(
    wait=wait_random_exponential(min=60, max=100),
    stop=stop_after_attempt(5),
    retry=retry_if_exception_type(
        Exception
    ),  # You can be more specific if you import OpenAIError
)
def _call_openai_with_retry(model, messages, response_format):
    """
    Call the OpenAI chat completions endpoint with exponential backoff retry.

    Retries up to 5 times on any exception, waiting between 60 and 100
    seconds (randomly jittered) between attempts.

    Args:
        model (str): OpenAI model identifier (e.g. ``"gpt-4o-mini"``).
        messages (list[dict]): List of message dicts in OpenAI chat format.
        response_format (dict): Response format specifier passed directly to
            the API (e.g. ``{"type": "json_object"}``).

    Returns:
        openai.types.chat.ChatCompletion: The raw API response object.
    """
    return _get_openai_client().chat.completions.create(
        model=model, messages=messages, response_format=response_format
    )


def get_llm_decision(
    state,
    *,
    llm_client=None,
    model="gpt-5-mini",
    max_changes=3,
    strict=None,
):
    """
    Use an LLM to select a negotiation partner and propose a joint action.

    Constructs a two-part prompt from the current game state: a static
    context containing the immutable game matrices (suitable for prompt
    caching) and a dynamic context containing only the current turn's
    mutable state. The LLM is instructed to return a JSON object specifying
    the chosen partner and both players' action vectors.

    The response is validated against game constraints:
    - Partner index must be a valid player index.
    - Action vectors must match the exact length for each involved player.
    - The number of 0→1 flips per player must not exceed ``max_changes``.

    Any invalid field is replaced with a zero vector or a random partner
    rather than raising an error. On total failure, a no-op action with a
    random partner is returned.

    Args:
        state (NegotiationState): Current game state, providing the policy
            matrix, goal matrix, satisfaction masks, turn index, and player
            metadata.

    Returns:
        tuple:
            - partner_idx (int): Index of the chosen negotiation partner.
            - joint_action (tuple[int]): Concatenated binary action vector
              for the proposer followed by the partner.
    """
    if strict is None:
        strict = llm_client is not None

    proposer = state.proposer()
    legal_partners = list(state.legal_negotiation_partners())
    if not legal_partners:
        raise ValueError("The current state has no legal negotiation partners.")

    # --- 1. System Prompt ---
    system_prompt = (
        "You are an expert strategic negotiator in a multi-issue bargaining game.\n"
        "You will receive the complete game state as a raw JSON object.\n\n"
        "--- STRATEGIC OBJECTIVES ---\n"
        "1. Maximize Proposer Utility: You must select the 'selected_partner_id', 'proposer_action_vector', and "
        "'partner_action_vector' that maximize the Proposer's Expected Terminal Reward.\n"
        "2. Ensure Partner Acceptance: The partner is rational. They will REJECT the joint action if they believe "
        "their expected terminal reward is higher by rejecting than accepting. "
        "You must propose a deal that is at least as good for the partner as rejection, or they will walk away.\n\n"
        "--- DATA SCHEMA ---\n"
        "1. 'G' (Goal Matrix): List of Lists [Goals][Players]. G[g][p] = Value of Goal g for Player p.\n"
        "2. 'P' (Agreement Matrix): List of Lists [Players][Actions]. P[p][a] = 1 if Player p committed to Action a (binding).\n"
        "3. 'sat_masks' (Satisfaction Masks): Dictionary {goal_index: Matrix}. If sat_masks[g][p][a] == 1, Action 'a' by Player 'p' is required for Goal 'g'.\n"
        "4. 'action_counts': Map of {Player ID: Total Available Actions}.\n\n"
        "5. 'binary_goals': Goal IDs whose satisfaction is all-or-nothing.\n\n"
        "--- HARD CONSTRAINTS ---\n"
        "1. Binding Actions: Bits in P can ONLY flip from 0 -> 1. Existing 1s must remain 1.\n"
        "2. Budget Limit: You can flip at most "
        + str(max_changes)
        + " NEW bits per player this turn.\n"
        "3. Vector Lengths: The output vectors must match the exact length of available actions for the specific players involved.\n"
        "4. Partner Constraint: selected_partner_id must not equal proposer_id.\n\n"
        "--- OUTPUT FORMAT ---\n"
        "Return ONLY a JSON object with this exact structure:\n"
        '{"selected_partner_id": int, "proposer_action_vector": [int list], "partner_action_vector": [int list]}'
    )

    # --- 2. STATIC CONTEXT (Static - CACHED) ---
    # This contains the heavy matrices (G, Masks).
    # Because this string is identical across turns, OpenAI will cache it.
    static_context_str = _build_static_context(state)

    # --- 3. DYNAMIC STATE (Dynamic - NOT CACHED) ---
    # This contains only what changes: P, Proposer ID, Turn Index.
    dynamic_state_str = _build_dynamic_state(state, proposer, max_changes)

    # --- 3. Call the API ---
    try:
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": "--- STATIC GAME CONTEXT ---\n" + static_context_str,
            },
            {
                "role": "user",
                "content": "--- CURRENT TURN STATE ---\n" + dynamic_state_str,
            },
        ]

        if llm_client is None:
            response = _call_openai_with_retry(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
        else:
            content = llm_client.complete(
                messages=messages,
                response_format={"type": "json_object"},
                model=model,
            )

        decision = _parse_json_object(content)
        partner_idx = _coerce_partner(state, decision.get("selected_partner_id"))
        p_action = _coerce_action(
            state,
            proposer,
            decision.get("proposer_action_vector"),
            max_changes=max_changes,
        )
        q_action = _coerce_action(
            state,
            partner_idx,
            decision.get("partner_action_vector"),
            max_changes=max_changes,
        )

        joint_action = tuple(p_action + q_action)

        return partner_idx, joint_action

    except Exception:
        if strict:
            raise
        # Set joint action to 0 vector and random partner on failure
        partner_idx = int(np.random.choice(legal_partners))
        p_action = _current_action(state, proposer)
        q_action = _current_action(state, partner_idx)

        joint_action = tuple(p_action + q_action)
        return partner_idx, joint_action


def _build_static_context(state):
    """
    Serialise the immutable parts of the game state to a JSON string.

    The returned string contains the game topology (player count, turn order,
    action counts) and the fixed matrices (G and satisfaction masks). Because
    this content does not change between turns, it is intended to be sent as
    a cached prefix in the prompt, reducing API costs.

    Args:
        state (NegotiationState): Current game state.

    Returns:
        str: JSON string with ``sort_keys=True`` to ensure identical output
            across calls (required for prompt cache hits).
    """

    def numpy_serializer(obj):
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.integer):
            return int(obj)
        return obj

    data = {
        "topology": {
            "num_players": state.n_players,
            "round_robin_order": state.round_robin,
            "action_counts": state.country_idx2num_actions,
            "legal_partners": state.legal_negotiation_partners(),
        },
        "matrices": {
            "G": state.G,
            # Using sort_keys=True in dumps ensures the string is identical every time (crucial for cache hits)
            "sat_masks": {str(k): v for k, v in state.sat_masks.items()},
            "binary_goals": sorted(state.binary_goals),
            "allowed_actions": getattr(state, "allowed_actions", None),
            "forbidden_actions": state.forbidden_actions,
        },
    }
    return json.dumps(data, default=numpy_serializer, sort_keys=True)


def _parse_json_object(content):
    """Parse strict JSON or a JSON object wrapped in a markdown fence."""
    if not isinstance(content, str):
        raise TypeError("LLM response content must be a string.")
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].lstrip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        return json.loads(cleaned[start : end + 1])


def _coerce_partner(state, raw_partner):
    """Return a legal partner, falling back to a legal random partner."""
    legal_partners = list(state.legal_negotiation_partners())
    try:
        partner = int(raw_partner)
    except (TypeError, ValueError):
        partner = None
    if partner in legal_partners:
        return partner
    return int(np.random.choice(legal_partners))


def _current_action(state, player_idx):
    """Return the current binding action vector for one player."""
    n_actions = state.country_idx2num_actions[player_idx]
    return state.P[player_idx, :n_actions].astype(int).tolist()


def _coerce_action(state, player_idx, raw_action, *, max_changes):
    """Turn an LLM action into a binding, budget-feasible action vector."""
    n_actions = state.country_idx2num_actions[player_idx]
    current = state.P[player_idx, :n_actions].astype(int)

    if not isinstance(raw_action, (list, tuple, np.ndarray)):
        return current.tolist()

    try:
        action = np.asarray(raw_action, dtype=float)
    except (TypeError, ValueError):
        return current.tolist()

    if action.shape != (n_actions,) or not np.all(np.isfinite(action)):
        return current.tolist()
    if not np.all(np.isin(action, [0.0, 1.0])):
        return current.tolist()

    action = np.maximum(current, action.astype(np.uint8))
    allowed = getattr(state, "allowed_actions", None)
    forbidden = getattr(state, "forbidden_actions", None)
    new_bits = current == 0
    if allowed is not None:
        action[new_bits & (np.asarray(allowed[player_idx, :n_actions]) != 1)] = 0
    if forbidden is not None:
        action[new_bits & (np.asarray(forbidden[player_idx, :n_actions]) == 1)] = 0

    if int(np.count_nonzero((action == 1) & new_bits)) > max_changes:
        return current.tolist()
    return action.astype(int).tolist()


def _build_dynamic_state(state, proposer, max_changes):
    """
    Serialise the mutable parts of the game state to a JSON string.

    The returned string contains only what changes between turns: the current
    turn index, the proposer's player ID, the action budget, and the current
    agreement matrix P. This should be sent as the final (non-cached) message
    in the prompt.

    Args:
        state (NegotiationState): Current game state.
        proposer (int): Index of the current proposing player.
        max_changes (int): Maximum number of 0→1 action flips allowed this
            turn.

    Returns:
        str: JSON string of the dynamic state.
    """

    def numpy_serializer(obj):
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.integer):
            return int(obj)
        return obj

    data = {
        "current_turn": state.idx,
        "proposer_id": proposer,
        "max_changes_allowed": max_changes,
        "current_agreement_matrix_P": state.P,
    }
    return json.dumps(data, default=numpy_serializer, sort_keys=True)


def _build_raw_state_description(state, proposer, max_changes):
    """
    Serialise the complete game state into a single JSON string.

    Combines metadata, topology, and all matrices (G, P, sat_masks) into one
    payload. Unlike ``_build_static_context`` and ``_build_dynamic_state``,
    this function does not split static from dynamic content and is not
    optimised for prompt caching.

    Args:
        state (NegotiationState): Current game state.
        proposer (int): Index of the current proposing player.
        max_changes (int): Maximum number of 0→1 action flips allowed this
            turn.

    Returns:
        str: JSON string of the full game state.
    """

    def numpy_serializer(obj):
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        return obj

    data_payload = {
        "meta": {
            "current_turn_index": state.idx,
            "total_turns": len(state.round_robin),
            "proposer_id": proposer,
            "max_changes_allowed": max_changes,
        },
        "topology": {
            "num_players": state.n_players,
            "round_robin_order": state.round_robin,
            "action_counts": state.country_idx2num_actions,
        },
        "matrices": {
            "G": state.G,
            "P": state.P,
            "sat_masks": {str(k): v for k, v in state.sat_masks.items()},
        },
    }
    return json.dumps(data_payload, default=numpy_serializer)
