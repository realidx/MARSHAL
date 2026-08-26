# Hidden Choice diagnostic

The report separates strict envelope compliance, recoverable semantic actions, and VOI policy metrics. VOI metrics are computed only for trajectories whose first action is semantically recoverable. Matched hidden/full metrics are reported only when family_id agrees exactly.

| Margin | Condition | Mode | N | Strict | Semantic | VOI cov. | ASK | Over-query | Under-query | Under-query
(full-info correct) | Query selection | Post-query act | VOI success | Full-info act | Protocol fail |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| -0.05 | no_query | hidden | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 85.0% | N/A | 0.0% |
| -0.05 | no_query | full | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | N/A | 85.0% | 85.0% | 0.0% |
| +0.05 | necessary_query | hidden | 20 | 95.0% | 95.0% | 95.0% | 26.3% | 0.0% | 73.7% | 58.3% | 100.0% | 80.0% | 21.1% | N/A | 5.0% |
| +0.05 | necessary_query | full | 20 | 95.0% | 95.0% | 95.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | N/A | 42.1% | 40.0% | 5.0% |
| -0.05 | irrelevant_uncertainty | hidden | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 100.0% | N/A | 0.0% |
| -0.05 | irrelevant_uncertainty | full | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | N/A | 95.0% | 95.0% | 0.0% |
| +0.05 | selective_query | hidden | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 100.0% | N/A | N/A | 0.0% | N/A | 0.0% |
| +0.05 | selective_query | full | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | N/A | 45.0% | 45.0% | 0.0% |
| -0.25 | no_query | hidden | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 80.0% | N/A | 0.0% |
| -0.25 | no_query | full | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | N/A | 80.0% | 80.0% | 0.0% |
| +0.25 | necessary_query | hidden | 20 | 100.0% | 100.0% | 100.0% | 25.0% | 0.0% | 75.0% | 75.0% | 100.0% | 100.0% | 25.0% | N/A | 0.0% |
| +0.25 | necessary_query | full | 20 | 95.0% | 95.0% | 95.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | N/A | 68.4% | 65.0% | 5.0% |
| -0.25 | irrelevant_uncertainty | hidden | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 100.0% | N/A | 0.0% |
| -0.25 | irrelevant_uncertainty | full | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | N/A | 95.0% | 95.0% | 0.0% |
| +0.25 | selective_query | hidden | 20 | 100.0% | 100.0% | 100.0% | 15.0% | 0.0% | 85.0% | 83.3% | 100.0% | 100.0% | 15.0% | N/A | 0.0% |
| +0.25 | selective_query | full | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | N/A | 75.0% | 75.0% | 0.0% |
| -1.00 | no_query | hidden | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 80.0% | N/A | 0.0% |
| -1.00 | no_query | full | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | N/A | 80.0% | 80.0% | 0.0% |
| +1.00 | necessary_query | hidden | 20 | 100.0% | 100.0% | 100.0% | 45.0% | 0.0% | 55.0% | 50.0% | 100.0% | 100.0% | 45.0% | N/A | 0.0% |
| +1.00 | necessary_query | full | 20 | 90.0% | 90.0% | 90.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | N/A | 72.2% | 65.0% | 10.0% |
| -1.00 | irrelevant_uncertainty | hidden | 20 | 95.0% | 95.0% | 95.0% | 0.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 100.0% | N/A | 5.0% |
| -1.00 | irrelevant_uncertainty | full | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | N/A | 100.0% | 100.0% | 0.0% |
| +1.00 | selective_query | hidden | 20 | 85.0% | 85.0% | 85.0% | 11.8% | 0.0% | 88.2% | 77.8% | 100.0% | 100.0% | 11.8% | N/A | 15.0% |
| +1.00 | selective_query | full | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | N/A | 60.0% | 60.0% | 0.0% |

## P(ASK | oracle margin)

| Delta | N | Ask rate |
|---:|---:|---:|
| -1.00 | 40 | 0.0% |
| -0.25 | 40 | 0.0% |
| -0.05 | 40 | 0.0% |
| +0.05 | 40 | 12.8% |
| +0.25 | 40 | 20.0% |
| +1.00 | 40 | 29.7% |

## Matched hidden/full control

Exact family matches: 140
Under-query rate conditioned on matched full-info correctness: 36.4%
