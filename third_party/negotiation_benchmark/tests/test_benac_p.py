import json

import numpy as np
import pytest

from benac_p import (
    ActionRef,
    GameRunner,
    GameSpec,
    GameState,
    Goal,
    OraclePolicy,
    Offer,
    OfferProposal,
    PassProposal,
    RandomPolicy,
    PerfectInfoSolver,
    ResponseAction,
    ScriptedPolicy,
    VLLMPlayerPolicy,
    build_player_observation,
    generate_game,
)
from benac_p.generator import GeneratorConfig
from benac_p.state import InvalidActionError
from methods.vllm_client import (
    OpenAICompatibleNegotiationClient,
    VLLMChatCompletion,
    VLLMNegotiationClient,
    VLLMToolCall,
)


def make_spec(round_robin=(0, 1, 2, 0)):
    goals = (
        Goal(0, (ActionRef(0, 0), ActionRef(1, 0))),
        Goal(1, (ActionRef(1, 1), ActionRef(2, 0))),
        Goal(2, (ActionRef(0, 1), ActionRef(2, 1))),
    )
    preferences = np.asarray(
        [
            [1, -1, 0],
            [1, 0, -1],
            [-1, 1, 0],
        ],
        dtype=np.int8,
    )
    return GameSpec(
        n_players=3,
        n_actions_per_player=(2, 2, 2),
        goals=goals,
        private_preferences=preferences,
        round_robin=tuple(round_robin),
        max_changes=1,
        seed=11,
    )


def make_two_player_spec(preferences, round_robin=(0,)):
    return GameSpec(
        n_players=2,
        n_actions_per_player=(1, 1),
        goals=(Goal(0, (ActionRef(0, 0), ActionRef(1, 0))),),
        private_preferences=np.asarray(preferences, dtype=np.int8),
        round_robin=tuple(round_robin),
        max_changes=1,
        seed=23,
    )


def test_generator_is_deterministic_and_satisfies_constraints():
    config = GeneratorConfig(n_rounds=4)
    first = generate_game(seed=7, config=config)
    second = generate_game(seed=7, config=config)
    assert first.goals == second.goals
    assert first.round_robin == second.round_robin
    np.testing.assert_array_equal(first.private_preferences, second.private_preferences)
    assert len(first.round_robin) == first.n_players * config.n_rounds
    assert all(np.any(row == 1) for row in first.private_preferences)
    assert all(np.any(first.private_preferences[:, goal_id] != 0) for goal_id in range(first.n_goals))
    requirement_sets = [frozenset(goal.required_actions) for goal in first.goals]
    assert len(requirement_sets) == len(set(requirement_sets))
    assert first.metadata["connected"] is True
    assert all(
        any(action.player_id == player_id for goal in first.goals for action in goal.required_actions)
        for player_id in range(first.n_players)
    )


def test_offer_validation_binding_pass_and_response_transitions():
    state = GameState(make_spec())
    assert all(
        sum(offer.proposer_action) + sum(offer.partner_action) > 0
        for offer in state.legal_offers(1)
    )
    accepted_offer = Offer(partner_id=1, proposer_action=(1, 0), partner_action=(1, 0))
    assert state.validate_offer(accepted_offer) == (1, 1)
    state.resolve_offer(accepted_offer, ResponseAction.ACCEPT)
    assert state.turn_index == 1
    assert state.commitments.tolist() == [[1, 0], [1, 0], [0, 0]]

    rejected_offer = Offer(partner_id=2, proposer_action=(0, 0), partner_action=(1, 0))
    with pytest.raises(InvalidActionError, match="unset"):
        state.validate_offer(rejected_offer)

    state.apply_pass()
    assert state.turn_index == 2
    rejected_offer = Offer(partner_id=0, proposer_action=(0, 1), partner_action=(1, 1))
    before = state.snapshot_commitments()
    state.resolve_offer(rejected_offer, "REJECT")
    assert state.snapshot_commitments() == before
    assert state.transcript[-1].response == "REJECT"

    state.apply_pass()
    with pytest.raises(InvalidActionError, match="no-op"):
        GameState(make_spec(round_robin=(0,))).validate_offer(
            Offer(partner_id=1, proposer_action=(0, 0), partner_action=(0, 0))
        )


def test_runner_accepts_arbitrary_scripted_and_random_policies():
    accepted = Offer(partner_id=1, proposer_action=(1, 0), partner_action=(1, 0))
    follow_up = Offer(partner_id=0, proposer_action=(0, 1), partner_action=(1, 1))
    policies = {
        0: ScriptedPolicy(proposals=(OfferProposal(accepted), PassProposal()), responses=("REJECT",)),
        1: ScriptedPolicy(proposals=(PassProposal(),), responses=("ACCEPT",)),
        2: ScriptedPolicy(proposals=(OfferProposal(follow_up),)),
    }
    result = GameRunner(make_spec(), policies).run()
    assert len(result.transcript) == 4
    assert result.transcript[0].response == "ACCEPT"
    assert result.transcript[1].action == "PASS"
    assert result.transcript[2].response == "REJECT"
    assert result.transcript[3].action == "PASS"
    assert result.invalid_action_count == 0

    random_result = GameRunner(
        make_spec(round_robin=(0, 1, 2)),
        [RandomPolicy(seed=player_id, pass_probability=0.0) for player_id in range(3)],
    ).run()
    assert len(random_result.transcript) == 3


def test_private_observation_hides_other_preferences_by_default():
    state = GameState(make_spec(round_robin=(0,)))
    private = build_player_observation(state, 0)
    assert private.own_preferences is not None
    assert private.all_preferences is None
    assert "all_preferences" not in private.to_dict()
    assert private.to_dict()["own_preferences"] == ["WANT", "AVOID", "NEUTRAL"]

    full = build_player_observation(state, 0, mode="full")
    assert full.all_preferences is not None
    assert len(full.all_preferences) == 3
    public = build_player_observation(state, 0, mode="public")
    assert public.own_preferences is None


def test_non_strict_invalid_proposal_becomes_public_invalid_pass():
    class InvalidPolicy:
        def propose(self, observation):
            del observation
            return OfferProposal(Offer(partner_id=1, proposer_action=(0, 0), partner_action=(0, 0)))

        def respond(self, observation, proposal):
            del observation, proposal
            return ResponseAction(ResponseAction.ACCEPT)

    result = GameRunner(
        make_spec(round_robin=(0,)),
        [InvalidPolicy(), RandomPolicy(seed=1), RandomPolicy(seed=2)],
        strict=False,
    ).run()
    assert result.invalid_action_count == 1
    assert result.transcript[0].action == "PASS"
    assert result.transcript[0].invalid_action is True


def test_perfect_info_solver_supports_pass_and_weak_acceptance_tiebreak():
    cooperative_spec = make_two_player_spec([[1], [1]])
    cooperative_state = GameState(cooperative_spec)
    cooperative_solver = PerfectInfoSolver(cooperative_spec, max_states=1000)
    cooperative_result = cooperative_solver.solve(cooperative_state)
    assert isinstance(cooperative_result.proposal, OfferProposal)
    evaluation = cooperative_solver.response_for_offer(
        cooperative_state,
        cooperative_result.proposal.offer,
    )
    assert evaluation.response.value == "ACCEPT"
    assert evaluation.accept_values == (1, 1)
    assert evaluation.reject_values == (0, 0)
    assert cooperative_state.snapshot_commitments() == ((0,), (0,))

    rollout = cooperative_solver.rollout(cooperative_state)
    assert rollout.final_commitments == ((1,), (1,))
    assert rollout.terminal_rewards == (1, 1)

    conflict_spec = make_two_player_spec([[1], [-1]])
    conflict_solver = PerfectInfoSolver(conflict_spec, max_states=1000)
    conflict_result = conflict_solver.solve(GameState(conflict_spec))
    assert isinstance(conflict_result.proposal, PassProposal)
    conflict_evaluation = conflict_solver.response_for_offer(
        GameState(conflict_spec),
        Offer(partner_id=1, proposer_action=(1,), partner_action=(1,)),
    )
    assert conflict_evaluation.response.value == "REJECT"


def test_rational_oracle_policy_runs_through_the_same_runner():
    spec = make_two_player_spec([[1], [1]])
    solver = PerfectInfoSolver(spec, max_states=1000)
    result = GameRunner(
        spec,
        {0: OraclePolicy(solver), 1: OraclePolicy(solver)},
    ).run()
    assert result.transcript[0].action == "OFFER"
    assert result.transcript[0].response == "ACCEPT"
    assert result.terminal_rewards == (1, 1)


def test_vllm_player_policy_legacy_roll_fallback_uses_json_protocol():
    class FakeClient:
        def __init__(self):
            self.calls = []
            self.outputs = [
                json.dumps(
                    {
                        "action": "OFFER",
                        "partner_id": 1,
                        "proposer_action": [1, 0],
                        "partner_action": [1, 0],
                    }
                ),
                json.dumps({"response": "ACCEPT"}),
            ]

        def complete(self, messages, **kwargs):
            self.calls.append((messages, kwargs))
            return self.outputs.pop(0)

    state = GameState(make_spec(round_robin=(0,)))
    observation = build_player_observation(state, 0)
    client = FakeClient()
    policy = VLLMPlayerPolicy(client)
    proposal = policy.propose(observation)
    assert isinstance(proposal, OfferProposal)
    response = policy.respond(
        build_player_observation(
            state,
            1,
            pending_proposer_id=0,
            pending_offer=proposal.offer,
        ),
        proposal,
    )
    assert response.value == "ACCEPT"
    prompt_text = "\n".join(message["content"] for message in client.calls[0][0])
    assert '"own_preferences"' in prompt_text
    assert '"all_preferences"' not in prompt_text


def test_vllm_player_policy_uses_native_phase_tools():
    class FakeNativeClient:
        def __init__(self):
            self.calls = []
            self.outputs = [
                VLLMChatCompletion(
                    content="I will make a cooperative offer.",
                    tool_calls=(
                        VLLMToolCall(
                            name="OFFER",
                            arguments={
                                "partner": "P1",
                                "self_commitments": ["A0"],
                                "partner_commitments": ["A0"],
                            },
                        ),
                    ),
                    raw_message={},
                    usage={},
                ),
                VLLMChatCompletion(
                    content="The offer is acceptable.",
                    tool_calls=(VLLMToolCall(name="ACCEPT", arguments={}),),
                    raw_message={},
                    usage={},
                ),
            ]

        def complete(self, messages, **kwargs):
            raise AssertionError("native policy must not use legacy complete()")

        def complete_with_tools(self, messages, **kwargs):
            self.calls.append((messages, kwargs))
            return self.outputs.pop(0)

    state = GameState(make_spec(round_robin=(0,)))
    client = FakeNativeClient()
    policy = VLLMPlayerPolicy(client, model="test-model")
    proposal = policy.propose(build_player_observation(state, 0))
    assert isinstance(proposal, OfferProposal)
    response = policy.respond(
        build_player_observation(
            state,
            1,
            pending_proposer_id=0,
            pending_offer=proposal.offer,
        ),
        proposal.offer,
    )
    assert response == ResponseAction("ACCEPT")

    proposer_kwargs = client.calls[0][1]
    responder_kwargs = client.calls[1][1]
    assert [
        tool["function"]["name"] for tool in proposer_kwargs["tools"]
    ] == ["PASS", "OFFER"]
    assert all(tool["function"]["strict"] is True for tool in proposer_kwargs["tools"])
    assert [
        tool["function"]["name"] for tool in responder_kwargs["tools"]
    ] == ["ACCEPT", "REJECT"]
    assert proposer_kwargs["tool_choice"] == "auto"
    assert proposer_kwargs["parallel_tool_calls"] is False
    assert "response_format" not in proposer_kwargs
    prompt_text = "\n".join(message["content"] for message in client.calls[0][0])
    assert "standalone JSON action" in prompt_text
    assert '"own_preferences"' in prompt_text
    assert '"all_preferences"' not in prompt_text


def test_native_missing_tool_retries_once_then_accepts_explicit_pass():
    class RetryClient:
        def __init__(self):
            self.calls = []
            self.outputs = [
                VLLMChatCompletion("I should wait.", (), {}, {}),
                VLLMChatCompletion(
                    "",
                    (VLLMToolCall(name="PASS", arguments={}),),
                    {},
                    {},
                ),
            ]

        def complete(self, messages, **kwargs):
            raise AssertionError("native policy must not use legacy complete()")

        def complete_with_tools(self, messages, **kwargs):
            self.calls.append((messages, kwargs))
            return self.outputs.pop(0)

    client = RetryClient()
    policy = VLLMPlayerPolicy(client)
    proposal = policy.propose(build_player_observation(GameState(make_spec(round_robin=(0,))), 0))
    assert isinstance(proposal, PassProposal)
    assert len(client.calls) == 2
    assert client.calls[1][0][-1]["content"] == (
        "Your previous response did not contain one valid game action. "
        "Choose exactly one of the available actions."
    )
    metrics = policy.metrics()
    assert metrics["raw_valid_action_rate"] == 0.0
    assert metrics["after_retry_valid_action_rate"] == 1.0
    assert metrics["retry_count"] == 1


def test_native_illegal_offer_retries_and_final_missing_tool_is_invalid():
    class InvalidThenMissingClient:
        def __init__(self):
            self.outputs = [
                VLLMChatCompletion(
                    "",
                    (
                        VLLMToolCall(
                            name="OFFER",
                            arguments={
                                "partner": "P1",
                                "self_commitments": [],
                                "partner_commitments": [],
                            },
                        ),
                    ),
                    {},
                    {},
                ),
                VLLMChatCompletion("still no action", (), {}, {}),
            ]

        def complete(self, messages, **kwargs):
            raise AssertionError("native policy must not use legacy complete()")

        def complete_with_tools(self, messages, **kwargs):
            return self.outputs.pop(0)

    policy = VLLMPlayerPolicy(InvalidThenMissingClient())
    result = GameRunner(
        make_spec(round_robin=(0,)),
        [policy, RandomPolicy(seed=1), RandomPolicy(seed=2)],
        strict=False,
    ).run()
    assert result.invalid_action_count == 1
    assert result.transcript[0].action == "PASS"
    assert result.transcript[0].invalid_action is True
    assert policy.metrics()["final_invalid_count"] == 1


def test_vllm_client_supports_fake_sync_and_async_engines():
    class Completion:
        def __init__(self, text):
            self.text = text

    class Output:
        def __init__(self, text):
            self.outputs = [Completion(text)]

    class SyncModel:
        def generate(self, prompts, sampling_params, use_tqdm):
            assert len(prompts) == 1
            assert sampling_params == "sampling"
            assert use_tqdm is False
            return [Output("sync")]

    sync_client = VLLMNegotiationClient(SyncModel(), sampling_params="sampling")
    assert sync_client.complete([{"role": "user", "content": "hello"}]) == "sync"

    class AsyncModel:
        async def generate(self, prompt, sampling_params, request_id):
            assert prompt
            assert sampling_params == "sampling"
            assert request_id
            yield Output("async")

    async_client = VLLMNegotiationClient(
        AsyncModel(),
        sampling_params="sampling",
        async_mode=True,
    )
    assert async_client.complete([{"role": "user", "content": "hello"}]) == "async"


def test_openai_compatible_vllm_client_posts_to_chat_completions(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            del exc_type, exc_value, traceback
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "I will wait.",
                                "tool_calls": [
                                    {
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {
                                            "name": "PASS",
                                            "arguments": "{}",
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = OpenAICompatibleNegotiationClient(
        "http://localhost:8000",
        "test-model",
        api_key="test-key",
        timeout=17,
        temperature=0.2,
        max_tokens=64,
    )
    result = client.complete_with_tools(
        [{"role": "user", "content": "hello"}],
        tools=(
            {
                "type": "function",
                "function": {
                    "name": "PASS",
                    "description": "wait",
                    "parameters": {"type": "object"},
                },
            },
        ),
    )

    assert result.content == "I will wait."
    assert result.tool_calls[0].name == "PASS"
    assert result.tool_calls[0].arguments == {}
    assert result.tool_calls[0].tool_call_id == "call_1"
    assert captured["url"] == "http://localhost:8000/v1/chat/completions"
    assert captured["timeout"] == 17.0
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["body"]["model"] == "test-model"
    assert captured["body"]["tools"][0]["function"]["name"] == "PASS"
    assert captured["body"]["tool_choice"] == "auto"
    assert captured["body"]["parallel_tool_calls"] is False
    assert "response_format" not in captured["body"]
    assert captured["body"]["stream"] is False


def test_openai_compatible_vllm_client_accepts_content_parts(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            del exc_type, exc_value, traceback
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": [
                                    {"type": "text", "text": '{"action":'},
                                    {"type": "text", "text": '"PASS"}'},
                                ]
                            }
                        }
                    ]
                }
            ).encode("utf-8")

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: FakeResponse())
    client = OpenAICompatibleNegotiationClient("http://localhost:8000/v1", "test-model")
    assert client.complete([{"role": "user", "content": "hello"}]) == '{"action":"PASS"}'


def test_malformed_vllm_output_is_marked_by_non_strict_runner():
    class BadClient:
        def complete(self, messages, **kwargs):
            del messages, kwargs
            return "not json"

    bad_policy = VLLMPlayerPolicy(BadClient())
    result = GameRunner(
        make_spec(round_robin=(0,)),
        [bad_policy, RandomPolicy(seed=1), RandomPolicy(seed=2)],
        strict=False,
    ).run()
    assert result.invalid_action_count == 1
    assert result.transcript[0].invalid_action is True
