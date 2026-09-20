"""Three training views of one frozen information set; no scaffold routing."""
from copy import deepcopy
import json
from training.social_mixed.prompt_clarification import request as history_request
from training.b_sft import social_named_probe as named


def request(task,arm='action_tools',variant=0):
    if arm!='action_tools':raise ValueError('Paired bank requires native tools')
    base=deepcopy(task['canonical_action_task'])
    result=history_request(base,arm,variant)
    text=result['messages'][1]['content']
    text=text.replace('Infer other players preferences from your visible information and choose your next action.','Choose your next action.')
    text=text.replace('Use only public history, your own preferences and your private investigation answers. Preserve uncertainty where evidence does not determine a preference.','')
    view=task['paired_view']
    if view=='Pplus':
        supplied=deepcopy(base);supplied['input']['supplied_belief']=task['input']['supplied_belief']
        visible=named.present(supplied,variant)
        text+='\n\nSUPPLIED BELIEF (inferred from the same visible information under the stated policy):\n'+json.dumps(visible['your_current_belief'],ensure_ascii=False)
    elif view=='B':
        visible=named.present(task,variant)
        text=text.split('RESPONSE INSTRUCTIONS')[0]
        text=text.replace('Choose your next action.','Assess the queried preference; do not take a game action.')
        br=named.request(task,arm,variant)
        text+='\nBELIEF QUESTION\n'+json.dumps(visible['belief_question'])+'\n'+str(visible['belief_rules'])
        if 'correct_previous_belief' in visible:
            text+='\nCORRECT PREVIOUS BELIEF (before the final new history segment):\n'+json.dumps(visible['correct_previous_belief'])
        text+='\nBriefly explain, then submit exactly one SUBMIT_BELIEFS call.'
        result['tools']=br['tools']
    elif view!='O':raise ValueError(view)
    result['messages'][1]['content']=text
    return result
