"""Prove that concise independent preference wording matches all frozen parents."""
from collections import Counter
from itertools import product
import json
from pathlib import Path
import numpy as np
from training.b_sft.social_private_teacher import PrivateInvestigationRules
from training.b_sft.preference_contract import world_weights
from training.strategic_slices.common import file_hash
from training.strategic_slices.named_prompt import check_independent_preferences
from examples.strategic_slices.export_terminal_prompt_preview import OUT


def main():
    if (OUT/'SNAPSHOT.json').exists():raise ValueError('Frozen evidence cannot be overwritten; use a new version')
    pool=Path('new/local_data/strategic_slices_oracle_consistent_candidates_v4')
    counts=Counter();rows=[];largest=0.
    for line in (pool/'parents.jsonl').read_text().splitlines():
        parent=json.loads(line);raw=parent['raw'];rules=PrivateInvestigationRules(raw)
        check_independent_preferences(rules)
        variable=[(p,g) for p,rs in rules.catalogues.items() for g in range(len(rs[0])) if len({r[g] for r in rs})>1]
        fixed=[(p,g) for p,rs in rules.catalogues.items() for g in range(len(rs[0])) if len({r[g] for r in rs})==1]
        w=raw['background_prior']['weights'];total=sum(w.values());names={1:'want',0:'neutral',-1:'avoid'}
        masses=np.array([np.prod([w[names[world[p][g]]]/total for p,g in variable]) for world in rules.worlds])
        old=world_weights(rules.worlds,raw['background_prior'])
        error=float(np.max(np.abs(masses-old)));largest=max(largest,error)
        assert np.isclose(masses.sum(),1.,rtol=0.,atol=1e-12)
        assert np.allclose(masses,old,rtol=0.,atol=1e-12)
        counts.update(parents=1,worlds=len(rules.worlds),variable_cells=len(variable),public_fixed_cells=len(fixed))
        rows.append(dict(parent_id=parent['id'],worlds=len(rules.worlds),variable_cells=len(variable),max_probability_error=error))
    report=dict(dataset_manifest_sha256=file_hash(pool/'manifest.json'),counts=dict(counts),
        all_catalogues_factorized=True,max_probability_error=largest,probability_tolerance=1e-12,
        corpus_changed=False,oracle_solved=False,model_called=False,gpu_tested=False,parents=rows)
    (OUT/'prior_equivalence.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='parents'},indent=2))


if __name__=='__main__':main()
