# Hidden Choice diagnostic

The report separates strict envelope compliance, recoverable semantic actions, and VOI policy metrics. VOI metrics are computed only for trajectories whose first action is semantically recoverable.

| Margin | Condition | Mode | N | Strict | Semantic | VOI cov. | ASK | Over-query | Under-query | Query selection | Post-query act | VOI success | Full-info act | Protocol fail |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| -0.05 | no_query | hidden | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 80.0% | N/A | 0.0% |
| -0.05 | no_query | full | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 80.0% | 80.0% | 0.0% |
| +0.05 | necessary_query | hidden | 20 | 95.0% | 100.0% | 100.0% | 25.0% | 0.0% | 75.0% | 100.0% | 100.0% | 20.0% | N/A | 0.0% |
| +0.05 | necessary_query | full | 20 | 95.0% | 95.0% | 95.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 42.1% | 40.0% | 5.0% |
| -0.05 | irrelevant_uncertainty | hidden | 20 | 90.0% | 95.0% | 95.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 89.5% | N/A | 5.0% |
| -0.05 | irrelevant_uncertainty | full | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 95.0% | 95.0% | 0.0% |
| +0.05 | selective_query | hidden | 20 | 85.0% | 95.0% | 95.0% | 5.3% | 0.0% | 94.7% | 100.0% | N/A | 0.0% | N/A | 5.0% |
| +0.05 | selective_query | full | 20 | 90.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 55.0% | 55.0% | 0.0% |
| -0.25 | no_query | hidden | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 80.0% | N/A | 0.0% |
| -0.25 | no_query | full | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 85.0% | 85.0% | 0.0% |
| +0.25 | necessary_query | hidden | 20 | 90.0% | 100.0% | 100.0% | 30.0% | 0.0% | 70.0% | 100.0% | 100.0% | 20.0% | N/A | 0.0% |
| +0.25 | necessary_query | full | 20 | 95.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 65.0% | 65.0% | 0.0% |
| -0.25 | irrelevant_uncertainty | hidden | 20 | 85.0% | 95.0% | 95.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 94.7% | N/A | 5.0% |
| -0.25 | irrelevant_uncertainty | full | 20 | 95.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 95.0% | 95.0% | 0.0% |
| +0.25 | selective_query | hidden | 20 | 90.0% | 90.0% | 90.0% | 11.1% | 0.0% | 88.9% | 50.0% | 100.0% | 5.6% | N/A | 10.0% |
| +0.25 | selective_query | full | 20 | 95.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 65.0% | 65.0% | 0.0% |
| -1.00 | no_query | hidden | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 85.0% | N/A | 0.0% |
| -1.00 | no_query | full | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 80.0% | 80.0% | 0.0% |
| +1.00 | necessary_query | hidden | 20 | 100.0% | 100.0% | 100.0% | 60.0% | 0.0% | 40.0% | 100.0% | 100.0% | 55.0% | N/A | 0.0% |
| +1.00 | necessary_query | full | 20 | 95.0% | 95.0% | 95.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 73.7% | 70.0% | 5.0% |
| -1.00 | irrelevant_uncertainty | hidden | 20 | 90.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 100.0% | N/A | 0.0% |
| -1.00 | irrelevant_uncertainty | full | 20 | 95.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 80.0% | 80.0% | 0.0% |
| +1.00 | selective_query | hidden | 20 | 90.0% | 100.0% | 100.0% | 15.0% | 0.0% | 85.0% | 100.0% | 100.0% | 15.0% | N/A | 0.0% |
| +1.00 | selective_query | full | 20 | 85.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 65.0% | 65.0% | 0.0% |

## P(ASK | oracle margin)

| Delta | N | Ask rate |
|---:|---:|---:|
| -1.00 | 40 | 0.0% |
| -0.25 | 40 | 0.0% |
| -0.05 | 40 | 0.0% |
| +0.05 | 40 | 15.4% |
| +0.25 | 40 | 21.1% |
| +1.00 | 40 | 37.5% |
