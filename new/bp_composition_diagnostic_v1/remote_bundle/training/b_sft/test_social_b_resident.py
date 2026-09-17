"""CPU checks for resident roles, including optimizer-only offload calls."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from roll.distributed.strategy.deepspeed_strategy import DeepSpeedTrainStrategy
from roll.distributed.strategy.hf_strategy import HfInferStrategy
from roll.utils.offload_states import OffloadStateType


class ResidentTests(unittest.TestCase):
    def test_resident_roles_never_move_states(self):
        for strategy in (DeepSpeedTrainStrategy, HfInferStrategy):
            role = strategy.__new__(strategy)
            role.worker_config = SimpleNamespace(keep_states_on_device=True)
            role.model = Mock()
            with patch('roll.distributed.strategy.hf_strategy.load_hf_model') as load, patch('roll.distributed.strategy.hf_strategy.offload_hf_model') as offload:
                for include in (None, [OffloadStateType.optimizer_states], [OffloadStateType.model_params]):
                    role.load_states(include=include)
                    role.offload_states(include=include)
                load.assert_not_called(); offload.assert_not_called()
            self.assertEqual(role.model.mock_calls, [])

    def test_nonresident_reference_still_moves(self):
        role = HfInferStrategy.__new__(HfInferStrategy)
        role.worker_config = SimpleNamespace(keep_states_on_device=False)
        role.model = None
        with patch('roll.distributed.strategy.hf_strategy.load_hf_model') as load, patch('roll.distributed.strategy.hf_strategy.offload_hf_model') as offload:
            role.load_states(); role.offload_states()
            load.assert_called_once(); offload.assert_called_once()


if __name__ == '__main__': unittest.main()
