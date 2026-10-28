from types import SimpleNamespace

import pytest

from training.b_sft.train import execute_mode, parse_args


BASE = ['--model', 'original', '--eval-file', 'validation.jsonl', '--output-dir', 'new-output']


def test_eval_needs_no_training_data():
    args = parse_args(BASE + ['--mode', 'eval'])
    assert args.train_file is None


@pytest.mark.parametrize('extra', [[], ['--mode', 'eval', '--resume', 'checkpoint-20'],
                                  ['--mode', 'eval', '--max-steps', '20']])
def test_invalid_mode_arguments_rejected(extra):
    with pytest.raises(SystemExit):
        parse_args(BASE + extra)


def test_eval_cannot_train_or_save_state():
    calls = []
    class Fake:
        def train(self, **kwargs):
            raise AssertionError('Must not train')
        def save_state(self):
            raise AssertionError('Must not save training state')
        def evaluate(self):
            calls.append('evaluate')
            return {'eval_loss': 0.7}
        def save_metrics(self, split, metrics):
            calls.append((split, metrics))
        def log_metrics(self, split, metrics):
            calls.append('log')
    execute_mode(Fake(), 'eval')
    assert calls == ['evaluate', ('eval', {'eval_loss': 0.7}), 'log']


def test_training_still_runs_before_evaluation():
    calls = []
    class Fake:
        def train(self, **kwargs):
            calls.append(('train', kwargs))
            return SimpleNamespace(metrics={})
        def save_state(self):
            calls.append('save_state')
        def evaluate(self):
            calls.append('evaluate')
            return {}
        def save_metrics(self, *args):
            pass
        def log_metrics(self, *args):
            pass
    execute_mode(Fake(), 'benchmark', 'checkpoint-20')
    assert calls == [('train', {'resume_from_checkpoint': 'checkpoint-20'}), 'save_state', 'evaluate']
    calls.clear()
    execute_mode(Fake(), 'train', skip_eval_loss=True)
    assert calls == [('train', {'resume_from_checkpoint': None}), 'save_state']


def test_fit_check_is_explicit_bounded_and_requires_identical_data():
    from training.b_sft.train import validate_fit_records
    base = ['--model', 'm', '--train-file', 't', '--eval-file', 't', '--output-dir', 'o',
            '--mode', 'train', '--fit-check']
    with pytest.raises(SystemExit):
        parse_args(base)
    assert parse_args(base + ['--max-steps', '24']).fit_check
    with pytest.raises(SystemExit):
        parse_args(base + ['--max-steps', '24', '--semantic-eval'])
    validate_fit_records([{'id':'a'}], [{'id':'a'}])
    with pytest.raises(ValueError, match='exactly the same'):
        validate_fit_records([{'id':'a'}], [{'id':'b'}])
    with pytest.raises(ValueError, match='nonempty'):
        validate_fit_records([], [])
