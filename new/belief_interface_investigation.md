# Belief-interface investigation: run 827142

Source: `runs/benac_semantic_diagnose/full-balanced-final128-827142`.
Comparison: `runs/benac_reasoning_calibration/826995` and
`runs/benac_semantic_diagnose/retry-826767`.

## Findings from saved responses

| Task family, full run | Tasks | Ordinary-text reasoning | Finalization |
|---|---:|---:|---:|
| B | 160 | 16 | 0 |
| P with oracle judgment | 160 | 160 | 11 |
| P with model judgment | 160 | 160 | 28 |

For all 160 B responses, saved tool arguments and scored preference sets agree.
Missing ordinary text is also absent from the server's saved `reasoning` and
`reasoning_content` fields. There is no evidence of client-side reasoning loss in
this archive; server-internal behavior cannot be established from saved responses.
All B outputs came from the initial auto-tool request, not bounded finalization.
The tool schema permits one, two, or three unique preferences and has no default
answer. Validation only checks and canonically orders the supplied set; it never
adds missing labels. Both task families use the same generation function,
`tool_choice=auto`, balanced system instruction, and initial 1024-token cap.

Full-run B outputs: all three labels in 123/160; WANT+AVOID in 26/160;
WANT only in 6/160; WANT+NEUTRAL in 5/160. Thus this is not a literal constant-output
implementation, although it strongly favors sets containing WANT.
All six confirmation known/root questions have empty histories and singleton
initial support, but receive all three labels. That failure does not require
partner-response inference and limits attribution of the post-response B failure.

## The problem was already visible in calibration

| Profile | B reasoning / 24 | Correct when all three remain / 8 | Correct when exclusion is required / 16 |
|---|---:|---:|---:|
| Open | 24 | 5 | 1 |
| Compact | 24 | 3 | 1 |
| Balanced | 2 | 8 | 0 |

Balanced's headline B exact of 33.3% comes entirely from the eight questions where
all three labels are correct. It is not evidence of improved evidence filtering.
Open and compact elicit text but still perform poorly on the exclusion subset:
restoring text alone is not known to solve the task. The 17 B questions shared
between the calibration selection and the full run have identical preference
sets and reasoning-presence flags under balanced. The absence of text therefore
predates finalization and reproduces on shared inputs.

Reconstructing the full suite verified all 480 request payload fingerprints and
all oracle labels. Recomputed scores and summaries match the archived JSON after
normalizing Python tuple/list representation. No scoring discrepancy was found.

## Prompt and interface risks

1. The B question ends with `Return all and only the still-possible values:
   want, neutral, avoid.` The colon and trailing enumeration can be read as the
   requested answer. P instead requests selection of one indexed action.
2. Balanced repeatedly emphasizes retaining possibilities, while only providing
   a soft instruction to reason. Auto tool calling permits immediate submission;
   it does not enforce reasoning before that submission. The observed profile
   difference supports investigating the prompt/interface interaction, not a
   claim that the wording alone is proven to cause the errors.
3. Known episodes still display all three population configurations and a generic
   equal-frequency description. Their singleton episode-specific prior is in
   `initially_possible_preferences`. This is logically sufficient when read as
   prior evidence, but the precedence is not explicit in the question.
4. The shared system prompt contains planning instructions even for B. This is a
   possible distraction, not an established cause. The first experiment retains
   it to avoid changing many components at once.
5. The base reasoning sentence and the profile sentence lack an intervening
   space (`arguments.For` / `arguments.Aim`). This is a formatting blemish shared
   by compact and balanced, not a demonstrated explanation of the difference.
   Historical prompts are left byte-identical for matched replay.

## Minimal discriminating experiment

`examples/benac_p/run_belief_interface_audit.sh` selects the first two discovery
bundles by ID, without selecting on answer quality: two known-root questions,
two unresolved-root questions, and six post-reference-action evidence questions.
It crosses original versus clarified question wording with immediate auto tools
versus a text-only reasoning request followed by named-tool submission.

The clarified question explains that the initial support is episode-specific
prior information and removes the trailing label enumeration; it provides no
oracle posterior or response interpretation. Both variants preserve the game,
history, support, labels, and schema. Staging changes the elicitation protocol,
not the substantive input. It retains the 1024-token initial cap and adds a
128-token submission cap. Original-auto results are cached; the other three
arms normally require 50 calls total, at most 60 including clear-auto truncation
recovery. Staged calls do not pretend their first response was truncated.

```bash
bash examples/benac_p/run_belief_interface_audit.sh \
  --source-run runs/benac_semantic_diagnose/full-balanced-final128-827142
```

The report separates known-copy, unresolved-prior, and evidence-update accuracy,
reasoning coverage, full-set frequency, and token cost. Resume preserves completed
answers, including wrong ones. No main-suite prompt or paper claim is changed by
this development audit. A gain on the known-copy check would remove one basic
interface concern; harder update failures remain legitimate diagnostic outcomes.

Remote results are pending. A locally successful export or mock test is not a
model experiment, and generating text does not establish faithful reasoning.
