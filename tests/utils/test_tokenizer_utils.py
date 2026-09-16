from roll.utils.tokenizer_utils import (
    extend_extra_special_tokens,
    get_extra_special_token_ids,
    get_extra_special_tokens,
)


class V5Tokenizer:
    extra_special_tokens = ["<existing>"]
    extra_special_tokens_ids = [10]

    def add_special_tokens(self, values, **kwargs):
        assert kwargs == {"replace_extra_special_tokens": False}
        self.extra_special_tokens.extend(values["extra_special_tokens"])
        return len(values["extra_special_tokens"])


class V4Tokenizer:
    additional_special_tokens = ["<existing>"]
    additional_special_tokens_ids = [10]

    def add_special_tokens(self, values, **kwargs):
        assert kwargs == {"replace_additional_special_tokens": False}
        self.additional_special_tokens.extend(values["additional_special_tokens"])
        return len(values["additional_special_tokens"])


def test_transformers_v5_extra_special_tokens():
    tokenizer = V5Tokenizer()
    assert get_extra_special_tokens(tokenizer) == ["<existing>"]
    assert get_extra_special_token_ids(tokenizer) == [10]
    assert extend_extra_special_tokens(tokenizer, ["<new>"]) == 1
    assert tokenizer.extra_special_tokens == ["<existing>", "<new>"]


def test_transformers_v4_additional_special_tokens():
    tokenizer = V4Tokenizer()
    assert get_extra_special_tokens(tokenizer) == ["<existing>"]
    assert get_extra_special_token_ids(tokenizer) == [10]
    assert extend_extra_special_tokens(tokenizer, ["<new>"]) == 1
    assert tokenizer.additional_special_tokens == ["<existing>", "<new>"]


def test_ids_fall_back_to_token_conversion():
    class MinimalTokenizer:
        extra_special_tokens = ["<a>", "<b>"]

        @staticmethod
        def convert_tokens_to_ids(tokens):
            assert tokens == ["<a>", "<b>"]
            return [20, 21]
