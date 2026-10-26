from __future__ import annotations

import pytest

from app.shortcode import ALPHABET, is_valid_alias, random_code


def test_random_code_length_and_alphabet():
    code = random_code(9)
    assert len(code) == 9
    assert set(code) <= set(ALPHABET)


def test_random_code_rejects_short_lengths():
    with pytest.raises(ValueError):
        random_code(3)


@pytest.mark.parametrize("alias", ["abc", "spring-sale", "A_1-b", "x" * 32])
def test_valid_aliases(alias):
    assert is_valid_alias(alias)


@pytest.mark.parametrize("alias", ["ab", "x" * 33, "has space", "slash/no", "API", "healthz", "docs"])
def test_invalid_or_reserved_aliases(alias):
    assert not is_valid_alias(alias)
