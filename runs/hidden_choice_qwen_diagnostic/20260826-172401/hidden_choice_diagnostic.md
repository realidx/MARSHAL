# Hidden Choice diagnostic

The report separates strict envelope compliance, recoverable semantic actions, and VOI policy metrics. VOI metrics are computed only for trajectories whose first action is semantically recoverable.

| Margin | Condition | Mode | N | Strict | Semantic | VOI cov. | ASK | Over-query | Under-query | Query selection | Post-query act | VOI success | Full-info act | Protocol fail |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| -0.05 | no_query | hidden | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 80.0% | N/A | 0.0% |
| -0.05 | no_query | full | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 90.0% | 90.0% | 0.0% |
| +0.05 | necessary_query | hidden | 20 | 25.0% | 25.0% | 25.0% | 80.0% | 0.0% | 20.0% | 100.0% | 100.0% | 80.0% | N/A | 75.0% |
| +0.05 | necessary_query | full | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 90.0% | 90.0% | 0.0% |
| -0.05 | irrelevant_uncertainty | hidden | 20 | 10.0% | 10.0% | 10.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 100.0% | N/A | 90.0% |
| -0.05 | irrelevant_uncertainty | full | 20 | 75.0% | 75.0% | 75.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 100.0% | 75.0% | 25.0% |
| +0.05 | selective_query | hidden | 20 | 10.0% | 10.0% | 10.0% | 0.0% | 0.0% | 100.0% | N/A | N/A | 0.0% | N/A | 90.0% |
| +0.05 | selective_query | full | 20 | 90.0% | 90.0% | 90.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 94.4% | 85.0% | 10.0% |
| -0.25 | no_query | hidden | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 80.0% | N/A | 0.0% |
| -0.25 | no_query | full | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 90.0% | 90.0% | 0.0% |
| +0.25 | necessary_query | hidden | 20 | 50.0% | 50.0% | 55.0% | 100.0% | 0.0% | 0.0% | 100.0% | 90.0% | 81.8% | N/A | 50.0% |
| +0.25 | necessary_query | full | 20 | 95.0% | 95.0% | 95.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 94.7% | 90.0% | 5.0% |
| -0.25 | irrelevant_uncertainty | hidden | 20 | 5.0% | 5.0% | 5.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 100.0% | N/A | 95.0% |
| -0.25 | irrelevant_uncertainty | full | 20 | 80.0% | 80.0% | 80.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 100.0% | 80.0% | 20.0% |
| +0.25 | selective_query | hidden | 20 | 0.0% | 0.0% | 0.0% | N/A | N/A | N/A | N/A | N/A | N/A | N/A | 100.0% |
| +0.25 | selective_query | full | 20 | 95.0% | 95.0% | 95.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 94.7% | 90.0% | 5.0% |
| -1.00 | no_query | hidden | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 80.0% | N/A | 0.0% |
| -1.00 | no_query | full | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 85.0% | 85.0% | 0.0% |
| +1.00 | necessary_query | hidden | 20 | 35.0% | 35.0% | 40.0% | 87.5% | 0.0% | 12.5% | 100.0% | 100.0% | 75.0% | N/A | 65.0% |
| +1.00 | necessary_query | full | 20 | 95.0% | 95.0% | 95.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 100.0% | 95.0% | 5.0% |
| -1.00 | irrelevant_uncertainty | hidden | 20 | 10.0% | 10.0% | 10.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 100.0% | N/A | 90.0% |
| -1.00 | irrelevant_uncertainty | full | 20 | 85.0% | 85.0% | 85.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 100.0% | 85.0% | 15.0% |
| +1.00 | selective_query | hidden | 20 | 5.0% | 5.0% | 5.0% | 0.0% | 0.0% | 100.0% | N/A | N/A | 0.0% | N/A | 95.0% |
| +1.00 | selective_query | full | 20 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | N/A | N/A | 90.0% | 90.0% | 0.0% |

## P(ASK | oracle margin)

| Delta | N | Ask rate |
|---:|---:|---:|
| -1.00 | 40 | 0.0% |
| -0.25 | 40 | 0.0% |
| -0.05 | 40 | 0.0% |
| +0.05 | 40 | 57.1% |
| +0.25 | 40 | 100.0% |
| +1.00 | 40 | 77.8% |
