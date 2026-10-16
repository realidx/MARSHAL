"""Small objective/estimator counterexamples, not a model-convergence test.

Run from the repository root. Uses no model, training data, or GPU.
"""
import json
import math
from pathlib import Path


def loo(rewards):
    return [r-(sum(rewards)-r)/(len(rewards)-1) for r in rewards]


def kl_optimum(rewards, reference, beta):
    logits=[math.log(p)+r/beta for p,r in zip(reference,rewards)]
    maximum=max(logits);weights=[math.exp(v-maximum) for v in logits]
    return [w/sum(weights) for w in weights]


def main():
    q=[1.,.99,0.];binary=[1.,0.,0.]
    examples=[]
    for reference in ([1/3]*3,[.001,.998,.001]):
        continuous=kl_optimum(q,reference,.01)
        discrete=kl_optimum(binary,reference,.01)
        examples.append(dict(Q=q,reference=reference,beta=.01,
            continuous_reward_optimum=continuous,binary_reward_optimum=discrete,
            continuous_greedy_action=max(range(3),key=lambda a:continuous[a]),
            binary_greedy_action=max(range(3),key=lambda a:discrete[a])))
    assert examples[1]['continuous_greedy_action']==1
    assert examples[1]['binary_greedy_action']==0
    wrong_scores=[.2,.4,.7]
    contrast=dict(sampled_Q=wrong_scores,unsampled_optimal_Q=1.,
        binary_LOO_advantages=loo([0.,0.,0.]),continuous_LOO_advantages=loo(wrong_scores),
        identical_wrong_continuous_LOO_advantages=loo([.4]*8))
    assert contrast['binary_LOO_advantages']==[0.]*3
    assert any(abs(a)>1e-10 for a in contrast['continuous_LOO_advantages'])
    assert max(abs(a) for a in contrast['identical_wrong_continuous_LOO_advantages'])<1e-12
    # Execute the real CPU advantage implementation on identical failed paths.
    from training.strategic_slices.terminal_training import binary_advantages
    local,baseline=binary_advantages([[0,1] for _ in range(8)])
    assert local==[[-.5,.5] for _ in range(8)]
    credit=dict(all_eight_step_rewards=[[0,1] for _ in range(8)],current_local_advantages=local,
        trajectory_average_baselines=baseline,whole_window_success_rewards=[0]*8,
        whole_window_success_LOO_advantages=loo([0.]*8))
    # A true-terminal-optimal first action can end the game immediately; a
    # slightly suboptimal one permits two more locally optimal decisions.
    horizon=dict(A=dict(terminal_utility=1.,local_binary_rewards=[1],local_continuous_rewards=[1.]),
        B=dict(terminal_utility=.99,local_binary_rewards=[0,1,1],local_continuous_rewards=[.99,1.,1.]))
    assert horizon['A']['terminal_utility']>horizon['B']['terminal_utility']
    assert sum(horizon['A']['local_binary_rewards'])<sum(horizon['B']['local_binary_rewards'])
    assert sum(horizon['A']['local_continuous_rewards'])<sum(horizon['B']['local_continuous_rewards'])
    # A potential with zero terminal value telescopes to a constant for a
    # fixed initial state. It preserves the return ordering but cannot turn
    # identical outcome returns into nonzero episode-level LOO advantages.
    potentials=[[2.,1.,0.],[2.,3.,1.,0.]]
    shaped=[sum(b-a for a,b in zip(path,path[1:])) for path in potentials]
    assert shaped==[-2.,-2.] and loo(shaped)==[0.,0.]
    result=dict(scope='Algebraic checks only; not a convergence guarantee for PPO, LLMs, or the current token-level KL surrogate.',
        KL_single_state_examples=examples,sampled_reward_contrast=contrast,
        local_credit_counterexample=credit,variable_horizon_reward_counterexample=horizon,
        potential_shaping_all_failed_example=dict(potentials=potentials,shaped_returns=shaped,LOO_advantages=loo(shaped)))
    path=Path(__file__).with_name('algebraic_checks.json')
    path.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(output=str(path),checks_passed=True,model_calls=0,GPU_started=False)))


if __name__=='__main__':main()
