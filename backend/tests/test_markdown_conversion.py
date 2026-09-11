"""Unit tests for app/services/markdown_conversion.py."""

from unittest.mock import MagicMock

from app.services.markdown_conversion import convert_to_markdown


def _llm(response=None, side_effect=None):
    mock = MagicMock()
    if side_effect is not None:
        mock.chat.side_effect = side_effect
    else:
        mock.chat.return_value = response
    return mock


def test_returns_markdown_and_success_on_a_normal_response():
    llm = _llm(response="# Title\n\nSome content.")

    text, succeeded = convert_to_markdown("Title\n\nSome content.", llm)

    assert text == "# Title\n\nSome content."
    assert succeeded is True


def test_falls_back_to_original_text_on_llm_error():
    llm = _llm(side_effect=RuntimeError("provider unreachable"))

    text, succeeded = convert_to_markdown("original extracted text", llm)

    assert text == "original extracted text"
    assert succeeded is False


def test_falls_back_to_original_text_on_empty_llm_response():
    llm = _llm(response="")

    text, succeeded = convert_to_markdown("original extracted text", llm)

    assert text == "original extracted text"
    assert succeeded is False


def test_falls_back_to_original_text_on_whitespace_only_response():
    llm = _llm(response="   \n  ")

    text, succeeded = convert_to_markdown("original extracted text", llm)

    assert text == "original extracted text"
    assert succeeded is False


def test_empty_input_is_a_no_op_without_calling_the_llm():
    llm = _llm(response="should not matter")

    text, succeeded = convert_to_markdown("   ", llm)

    assert text == "   "
    assert succeeded is False
    llm.chat.assert_not_called()


def test_strips_surrounding_whitespace_from_a_successful_response():
    llm = _llm(response="\n\n# Title\n\nBody.\n\n")

    text, succeeded = convert_to_markdown("Title\n\nBody.", llm)

    assert text == "# Title\n\nBody."
    assert succeeded is True
