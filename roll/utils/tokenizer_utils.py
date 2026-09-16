def get_extra_special_tokens(tokenizer):
    """Return tokenizer extra special tokens across Transformers v4/v5."""
    if hasattr(tokenizer, "extra_special_tokens"):
        return list(tokenizer.extra_special_tokens)
    return list(getattr(tokenizer, "additional_special_tokens", []))


def get_extra_special_token_ids(tokenizer):
    """Return tokenizer extra special token IDs across Transformers v4/v5."""
    if hasattr(tokenizer, "extra_special_tokens_ids"):
        return list(tokenizer.extra_special_tokens_ids)
    if hasattr(tokenizer, "additional_special_tokens_ids"):
        return list(tokenizer.additional_special_tokens_ids)
    return list(tokenizer.convert_tokens_to_ids(get_extra_special_tokens(tokenizer)))


def extend_extra_special_tokens(tokenizer, tokens):
    """Mark tokens as extra special without replacing the existing set."""
    if not tokens:
        return 0
    if hasattr(tokenizer, "extra_special_tokens"):
        return tokenizer.add_special_tokens(
            {"extra_special_tokens": tokens}, replace_extra_special_tokens=False
        )
    return tokenizer.add_special_tokens(
        {"additional_special_tokens": tokens}, replace_additional_special_tokens=False
    )
