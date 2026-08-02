from dataclasses import dataclass, field

from roll.configs.base_config import BaseConfig
from roll.configs.worker_config import WorkerConfig


@dataclass
class DeviceMappedConfig(BaseConfig):
    actor: WorkerConfig = field(
        default_factory=lambda: WorkerConfig(device_mapping="list(range(0,2))")
    )


def test_two_device_indices_require_two_single_gpu_nodes():
    config = DeviceMappedConfig(num_gpus_per_node=1, sequence_length=1)
    assert config.num_nodes == 2


def test_two_device_indices_fit_on_one_two_gpu_node():
    config = DeviceMappedConfig(num_gpus_per_node=2, sequence_length=1)
    assert config.num_nodes == 1
