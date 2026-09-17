"""Public fixed-query contract, separate from the partner dynamics version."""
from copy import deepcopy

TASK_VERSION = 'social-fixed-queries-v1'
B_INSTRUCTION = (
    '逐项回答 queries 列出的所有伙伴偏好，每项恰好一次，不增加其他 player/goal。'
    '这些查询只由初始公开候选目录确定；即使后续证据已确定偏好，也仍须回答该项。'
    '公开确定的偏好保留在上下文中供规划使用，不作为输出项目。'
    '依据公开历史保留全部仍可能的偏好；按 favored_rule 判断倾向。'
    '先简短说明证据依据，再提交工具调用；不要求固定推理步骤，不输出概率或计数。')
FAVORED_RULE = dict(
    robustness_ratio=1.25,
    rule='Start from the uniform prior over unique joint catalogue worlds and filter by observed partner policy actions. '
         'A singleton favors its sole label. Otherwise favor the unique leading marginal label only when its '
         'remaining-world support exceeds 1.25 times the runner-up; equality or a tie means undetermined. '
         'This is stability to individual surviving-world weight multipliers in [1,1.25], not robustness to other partner policies. '
         'Do not output counts or probabilities.')


def fixed_context(context):
    """Queries depend only on public INITIAL catalogues, never on teacher B."""
    from training.b_sft.social_rollout import queries_for
    result = deepcopy(context)
    result['queries'] = queries_for({int(p): tuple(map(tuple, rows))
                                    for p, rows in result['public_type_catalogues'].items()}, result['player'])
    result['B_task_version'] = TASK_VERSION
    result['favored_rule'] = deepcopy(FAVORED_RULE)
    result['instruction'] = B_INSTRUCTION
    return result
