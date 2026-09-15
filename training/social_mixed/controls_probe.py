"""Eleven train-only counterexample checks; frozen v3 presentation, eight repeats."""
from training.social_mixed import contrast_probe

def main():
    contrast_probe.PACK = contrast_probe.ROOT / 'examples/social_bp/b_chronological_controls_v4'
    contrast_probe.REQUEST_FILES = ('requests.jsonl',)
    contrast_probe.EXPECTED_TASKS = 11
    contrast_probe.EXPECTED_REQUESTS = 11
    contrast_probe.main()

if __name__ == '__main__':
    main()
