# Hidden Choice diagnostic

The report separates strict envelope compliance, recoverable semantic actions, and VOI policy metrics. VOI metrics are computed only for trajectories whose first action is semantically recoverable.

| Margin | Condition | Mode | N | Strict | Semantic | VOI cov. | ASK | Over-query | Under-query | Query selection | Post-query act | VOI success | Full-info act | Protocol fail |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| -0.05 | no_query | hidden | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 80.0% | N/A | 0.0% |
| -0.05 | no_query | full | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 80.0% | 80.0% | 0.0% |
| +0.05 | necessary_query | hidden | 20 | 55.0% | 55.0% | 55.0% | 72.7% | 0.0% | 27.3% | 100.0% | 100.0% | 72.7% | N/A | 45.0% |
| +0.05 | necessary_query | full | 20 | 95.0% | 95.0% | 95.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 94.7% | 90.0% | 5.0% |
| -0.05 | irrelevant_uncertainty | hidden | 20 | 20.0% | 20.0% | 20.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 75.0% | N/A | 80.0% |
| -0.05 | irrelevant_uncertainty | full | 20 | 90.0% | 90.0% | 90.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 100.0% | 90.0% | 10.0% |
| +0.05 | selective_query | hidden | 20 | 10.0% | 10.0% | 10.0% | 0.0% | 0.0% | 100.0% | N/A | N/A | 0.0% | N/A | 90.0% |
| +0.05 | selective_query | full | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 85.0% | 85.0% | 0.0% |
| -0.25 | no_query | hidden | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 80.0% | N/A | 0.0% |
| -0.25 | no_query | full | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 85.0% | 85.0% | 0.0% |
| +0.25 | necessary_query | hidden | 20 | 60.0% | 60.0% | 60.0% | 91.7% | 0.0% | 8.3% | 100.0% | 100.0% | 91.7% | N/A | 40.0% |
| +0.25 | necessary_query | full | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 90.0% | 90.0% | 0.0% |
| -0.25 | irrelevant_uncertainty | hidden | 20 | 10.0% | 10.0% | 10.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 100.0% | N/A | 90.0% |
| -0.25 | irrelevant_uncertainty | full | 20 | 95.0% | 95.0% | 95.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 94.7% | 90.0% | 5.0% |
| +0.25 | selective_query | hidden | 20 | 10.0% | 10.0% | 10.0% | 50.0% | 0.0% | 50.0% | 100.0% | 100.0% | 50.0% | N/A | 90.0% |
| +0.25 | selective_query | full | 20 | 95.0% | 95.0% | 95.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 100.0% | 95.0% | 5.0% |
| -1.00 | no_query | hidden | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 80.0% | N/A | 0.0% |
| -1.00 | no_query | full | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 80.0% | 80.0% | 0.0% |
| +1.00 | necessary_query | hidden | 20 | 50.0% | 50.0% | 50.0% | 70.0% | 0.0% | 30.0% | 100.0% | 100.0% | 70.0% | N/A | 50.0% |
| +1.00 | necessary_query | full | 20 | 90.0% | 90.0% | 90.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 100.0% | 90.0% | 10.0% |
| -1.00 | irrelevant_uncertainty | hidden | 20 | 20.0% | 20.0% | 20.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 75.0% | N/A | 80.0% |
| -1.00 | irrelevant_uncertainty | full | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 90.0% | 90.0% | 0.0% |
| +1.00 | selective_query | hidden | 20 | 20.0% | 20.0% | 20.0% | 25.0% | 0.0% | 75.0% | 100.0% | 100.0% | 25.0% | N/A | 80.0% |
| +1.00 | selective_query | full | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 95.0% | 95.0% | 0.0% |

## P(ASK | oracle margin)

| Delta | N | Ask rate |
|---:|---:|---:|
| -1.00 | 40 | 0.0% |
| -0.25 | 40 | 0.0% |
| -0.05 | 40 | 0.0% |
| +0.05 | 40 | 61.5% |
| +0.25 | 40 | 85.7% |
| +1.00 | 40 | 57.1% |
