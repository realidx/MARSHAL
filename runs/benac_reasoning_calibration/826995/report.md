# Reasoning budget calibration

Matched discovery inputs. Open is the archived baseline; compact/balanced are new calls at the SAME hard token cap.
B/P success rates below require both a valid completion and a correct answer; no silent exclusion of truncations.
P targets use the supplied judgment, including frozen model judgments.

| Profile | Valid | Truncated | B valid + exact | P valid + optimal | Mean tokens | P95 tokens |
|---|---:|---:|---:|---:|---:|---:|
| open | 83.3% | 16.7% | 25.0% | 37.5% | 463.0 | 1024.0 |
| compact | 98.6% | 1.4% | 16.7% | 43.8% | 140.0 | 180.7 |
| balanced | 94.4% | 5.6% | 33.3% | 50.0% | 231.0 | 878.8 |

Provisional recommended profile: none yet; coverage or quality criteria not met.
Development heuristic: >=98% valid and within 5 percentage points of best observed B and P valid-and-correct rates; among eligible profiles choose lowest mean completion tokens. Not a noninferiority proof.

Invalid/truncated answers count as uncompleted successes, never as fabricated strategic actions. Regret on valid answers has different coverage across profiles. Planning is scored under its frozen supplied judgment. Only discovery inputs are used.
Freeze the selected setting before a fresh confirmation run. Historical-baseline comparisons assume the same model weights and serving configuration. Paired bundle-bootstrap intervals are in comparison.json.
