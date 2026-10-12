import pytest

from renpy_translator.exporter import quote
from renpy_translator.extractors import renpy_literal


@pytest.mark.parametrize(
    "text",
    [
        'Hello "friend"',
        "Line\nAnother",
        "Two  spaces",
        "Tab\tCarriage\r",
        r"Literal \t \n backslashes",
        "Olá [player] {b}Bem-vindo{/b}",
        "[[literal {{literal",
    ],
)
def test_catalog_literal_preserves_renpy_semantics(text):
    assert renpy_literal(quote(text)) == text


def test_renpy_native_escape_and_whitespace_rules():
    assert renpy_literal(r'"Hello   world\n\[literal\{literal\%"') == (
        "Hello world\n[[literal{{literal%%"
    )
    assert renpy_literal(r'r"Keep  spaces\n"') == r"Keep  spaces\n"
