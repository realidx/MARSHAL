"""Same paired diagnostic using chronological tables instead of a prefixed reminder."""
from training.social_mixed import contrast_probe

def main():
    contrast_probe.PACK = contrast_probe.ROOT / 'examples/social_bp/b_chronological_v3'
    contrast_probe.main()

if __name__ == '__main__':
    main()
