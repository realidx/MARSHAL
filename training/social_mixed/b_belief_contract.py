"""Tolerant qualitative B scoring; does not alter P belief certification."""
VERSION='b-near-top-0.1-v1'
RULES='''possible_preferences must include exactly the preferences compatible with the visible evidence, including unlikely ones. A direct truthful revelation leaves only its revealed value. Lack of a direct revelation does not mean lack of evidence: voluntary choices can rule out preferences under the stated choice rules; imposed events are not evidence of the player's preferences. Exclude a preference only when it is incompatible, not merely less likely. Without new informative evidence, retain the background belief after applying known facts and the stated constraints; do not assume equal support.
favored: If only one preference remains possible, report it. Otherwise, if the strongest support exceeds the second strongest by more than 10 percentage points, report the strongest preference. If that gap is at most 10 percentage points, either undetermined or any still-possible preference within 10 percentage points of the strongest support is accepted. Return qualitative labels only, not numerical probabilities.'''


def accepted_favored(mass):
    support=[k for k,v in mass.items() if v>0]
    if not support:raise ValueError('Empty belief support')
    if len(support)==1:return support
    ranked=sorted(support,key=lambda k:mass[k],reverse=True)
    if mass[ranked[0]]-mass[ranked[1]]>0.1+1e-9:return [ranked[0]]
    return ['undetermined']+[k for k in support if mass[ranked[0]]-mass[k]<=0.1+1e-9]
