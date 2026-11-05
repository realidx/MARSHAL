# Native800 D v1.1 package correction

This is a packaging/source-closure revision of native800-terminal-D-v1, created after Slurm job 1077848 failed during Python imports with ModuleNotFoundError for examples.strategic_slices.run_terminal_d. The job ended after 8 seconds before dataset initialization, model hashing, server startup, or any model request. Its stderr is retained with the v1 package.

The v1.1 package adds and pins run_terminal_d.py, which the v1 launcher already imports for model identity, vLLM command construction, and server cleanup. It uses versioned copies of the D runner and launchers so the new registration snapshot records this dependency. The v1.1 D formula, prompt-v4, response scorer-v1, frozen 800-entry set, parent references, sampling, and control-to-terminal contract are unchanged. Output must use a fresh runs/native800-D-v1.1 directory.

No CPU test, mock, GPU smoke test, or model test is run while preparing this package. The next authorized H100 execution is the first actual v1.1 model attempt.

Run command: bash examples/strategic_slices/run_native800_d_v1_1.sh --model /home/e/e1300530/models/Qwen3-4B-Instruct-2507 --output runs/native800-D-v1.1

For Slurm, submit examples/strategic_slices/sbatch_native800_d_v1_1.sh from the extracted package root, with the chosen GPU partition/resources. The job snapshot records the actual model/data/source identities and resolved evaluation contract. The package hash is kept in its external .json sidecar and the version index.
