"""Reuse the CalBench-owned vLLM lifecycle for Shape Factory."""
import sys
from examples.final_evaluation.launch_calbench_local import main
if __name__=='__main__':
    if '--suite' in sys.argv:raise SystemExit('Shape Factory wrapper selects its own suite')
    sys.argv.extend(['--suite','shapefactory'])
    main()
