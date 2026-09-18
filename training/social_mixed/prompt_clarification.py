"""Opt-in table semantics clarification; frozen releases remain unchanged."""
from copy import deepcopy
from training.social_mixed.reasoning_requests import request as original

VERSION='required-commitments-v1'

def clarify(text):
    lines=text.splitlines()
    index=lines.index('GOAL REQUIREMENTS BY PLAYER')
    cells=[x.strip() for x in lines[index+1].strip('|').split('|')]
    assert cells[:2]==['Goal','Scoring']
    cells=cells[:2]+[p+"'s required commitments" for p in cells[2:]]
    lines[index+1]='| '+' | '.join(cells)+' |'
    end=index+3
    while end<len(lines) and lines[end].startswith('|'):end+=1
    lines.insert(end,'Cells list required commitments, not player preferences. A commitment may contribute to multiple goals.')
    return '\n'.join(lines)

def request(task,arm='action_tools',variant=0):
    result=original(task,arm,variant)
    if task.get('prompt_clarification')==VERSION:
        result=deepcopy(result)
        result['messages'][1]['content']=clarify(result['messages'][1]['content'])
    return result
