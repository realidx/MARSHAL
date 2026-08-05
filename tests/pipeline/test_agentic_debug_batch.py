import pickle
from types import SimpleNamespace
from unittest.mock import Mock

from roll.pipeline.agentic.agentic_pipeline import AgenticPipeline, maybe_dump_debug_batch


def test_debug_batch_dump_is_a_noop_when_disabled(tmp_path):
    dumped = maybe_dump_debug_batch(
        batch={"large_tensor_placeholder": [1, 2, 3]},
        output_dir=str(tmp_path),
        global_step=7,
        enabled=False,
    )

    assert dumped is False
    assert not (tmp_path / "debug").exists()


def test_debug_batch_dump_remains_available_when_enabled(tmp_path):
    batch = {"small_debug_payload": [1, 2, 3]}
    dumped = maybe_dump_debug_batch(
        batch=batch,
        output_dir=str(tmp_path),
        global_step=7,
        enabled=True,
    )

    output_path = tmp_path / "debug" / "batch-7.pkl"
    assert dumped is True
    assert output_path.exists()
    with output_path.open("rb") as f:
        assert pickle.load(f) == batch


def test_final_evaluation_syncs_final_weights_without_training():
    pipeline = AgenticPipeline.__new__(AgenticPipeline)
    pipeline.pipeline_config = SimpleNamespace(
        eval_at_end=True,
        max_steps=200,
        adv_estimator="reinforce",
    )
    pipeline.actor_train = Mock()
    pipeline.model_update = Mock(return_value={"sync": 1.0})
    pipeline._run_evaluation = Mock(return_value={"val/score/mean": 0.5})
    pipeline.tracker = Mock()

    pipeline._run_final_evaluation()

    pipeline.actor_train.offload_states.assert_called_once_with(blocking=True)
    pipeline.model_update.assert_called_once_with(200)
    pipeline._run_evaluation.assert_called_once_with(200)
    pipeline.tracker.log.assert_called_once_with(
        values={"sync": 1.0, "val/score/mean": 0.5}, step=200
    )


def test_final_evaluation_is_optional():
    pipeline = AgenticPipeline.__new__(AgenticPipeline)
    pipeline.pipeline_config = SimpleNamespace(eval_at_end=False)
    pipeline.actor_train = Mock()

    pipeline._run_final_evaluation()

    pipeline.actor_train.offload_states.assert_not_called()
