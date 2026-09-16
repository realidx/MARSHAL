from roll.utils.collective.pg_utils import process_group_options_keyword


def test_current_process_group_helper_uses_backend_options():
    from torch.distributed.distributed_c10d import _new_process_group_helper

    assert process_group_options_keyword(_new_process_group_helper) == "backend_options"


def test_legacy_process_group_helper_uses_pg_options():
    def legacy_helper(
        group_size, group_rank, global_ranks_in_group, backend, store,
        group_name=None, pg_options=None, timeout=None,
    ):
        pass

    assert process_group_options_keyword(legacy_helper) == "pg_options"
