import pytest

from training.b_sft.preflight import device_tokens, select_devices


def rows():
    return [dict(index='0', uuid='GPU-a', **{'memory.free': '12000'}),
            dict(index='3', uuid='GPU-b', **{'memory.free': '20000'})]


@pytest.mark.parametrize('value', ['', '0,', '0,0'])
def test_explicit_distinct_selection_required(value):
    with pytest.raises(ValueError):
        device_tokens(value)


def test_selection_preserves_visible_device_order():
    selected = select_devices(device_tokens('GPU-b,0'), rows())
    assert [r['index'] for r in selected] == ['3', '0']


@pytest.mark.parametrize('tokens,minimum', [(['1'], 0), (['0', 'GPU-a'], 0), (['0'], 13000)])
def test_missing_alias_duplicate_and_memory_shortfall_rejected(tokens, minimum):
    with pytest.raises(ValueError):
        select_devices(tokens, rows(), minimum)


def test_no_fixed_sixteen_gb_requirement():
    assert len(select_devices(['0'], rows())) == 1
