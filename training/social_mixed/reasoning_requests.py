"""History-to-action tasks use existing rules/tools, without an oracle belief."""
from training.b_sft import social_named_probe as named
from training.b_sft import review_prompt as prompt


def request(task,arm='action_tools',variant=0):
    if task['input'].get('belief_source')!='history':return named.request(task,arm,variant)
    if arm!='action_tools':raise ValueError('History tasks require native action tools')
    v=named.present(task,variant)
    v.pop('your_current_belief',None)
    lines=['YOUR TASK',f'You are {v["you"]}.',
        'Infer other players preferences from your visible information and choose your next action.',
        '',prompt.game_rules(v),'',*prompt.layout(v),'','PREFERENCE CONDITIONS',prompt.preference_conditions(v),
        '', 'HOW OTHER PLAYERS CHOOSE',prompt.partner_policy(v),'',*prompt.chronology(v),'',*prompt.decision(v),
        '', 'RESPONSE INSTRUCTIONS',prompt.OBJECTIVE,
        'An action is acceptable if it loses at most 0.1 goal-completion points compared with the best action. When responses are equally good for you, the allowance for helping others is also 0.1 points in total.',
        'Use only public history, your own preferences and your private investigation answers. Preserve uncertainty where evidence does not determine a preference.',
        'Briefly explain your decision, then make exactly one registered game-action tool call. Keep the explanation outside the tool arguments.']
    return dict(messages=[dict(role='system',content=prompt.SYSTEM),dict(role='user',content='\n'.join(lines))],
        tools=named.action_tools(v),tool_choice='auto',parallel_tool_calls=False,max_tokens=1024)
