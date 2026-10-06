"""Per-request native output budget, retaining the historical 1024 default."""
def output_limit(request):
    value=request.get('max_tokens',1024)
    if type(value) is not int or value<1:
        raise ValueError('max_tokens must be a positive integer')
    return value


def check_context(prompt_length,request,context):
    limit=output_limit(request)
    if prompt_length+limit>context:
        raise ValueError(f'Prompt has {prompt_length} tokens plus output {limit}, context={context}; refusing truncation')
    return limit
