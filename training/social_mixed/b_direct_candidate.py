"""Opt-in B semantic clarification. Explanation-first contract is preserved.
Module name retained for compatibility with the initial candidate."""
from training.social_mixed.paired_requests import request as original_request
VERSION='b-explanation-first-semantics-v2'
def request(task, variant=0, clarify_semantics=True):
    if task.get('paired_view')!='B':raise ValueError('B only')
    result=original_request(task,variant=variant)
    if clarify_semantics:
        result['messages'][1]['content']+='\nBELIEF SEMANTICS\nWanting one goal does not rule out wanting another goal. Absence of an explicit statement is not evidence of avoidance. Background probabilities are evidence about relative support, not proof that a value is impossible. An observed commitment or offer need not reveal a preference for every goal it touches: evaluate the complete consequences and the stated choice rules, including ties and the partner response.'
    return result
