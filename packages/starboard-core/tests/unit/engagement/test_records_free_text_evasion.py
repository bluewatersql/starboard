"""Host free text (D3-24): obfuscated emails and ``sk-`` keys are rejected.

Folded for the email probe: ideographic / halfwidth / fullwidth full stops,
``[at]`` / ``(at)``, ``[.]`` / ``(.)`` and `` dot ``. Ordinary prose still passes.
Spaced-out letters (``j a n e @ ...``) are deliberately not folded.
"""

from __future__ import annotations

import pytest
from starboard_core.engagement.records import _check_free_text

OBFUSCATED_EMAILS = [
    "jane@example。com",  # ideographic full stop
    "jane@example｡com",  # halfwidth ideographic full stop
    "jane@example．com",  # fullwidth full stop
    "jane[at]example[.]com",
    "jane(at)example(.)com",
    "jane [AT] example [.] com",
    "jane@example dot com",
    "ask jane@example DOT co DOT uk",
]
CREDENTIALS = [
    "key sk-ant-" + "a1B2c3D4e5F6g7H8",
    "sk-" + "abcdefghijklmnop1234",
]
CLEAN = [
    "rate dropped after the fix at 3pm",
    "see the dot product",
    "the dot product of x and y at 3pm. Then rerun",
    "spill dropped (at) the join stage after the fix",
    "task-abcdefghijklmnopqrstu and risk-assessment-is-very-long",
    "job 42 @ 10:00 keeps failing",
    "x@y",
]


@pytest.mark.unit
@pytest.mark.parametrize("text", OBFUSCATED_EMAILS)
def test_obfuscated_emails_are_rejected(text: str) -> None:
    with pytest.raises(ValueError, match="email"):
        _check_free_text(text, "Case.question")


@pytest.mark.unit
@pytest.mark.parametrize("text", CREDENTIALS)
def test_sk_keys_are_rejected(text: str) -> None:
    with pytest.raises(ValueError, match="credential"):
        _check_free_text(text, "Case.question")


@pytest.mark.unit
@pytest.mark.parametrize("text", CLEAN)
def test_ordinary_prose_still_passes(text: str) -> None:
    _check_free_text(text, "Case.question")


#: Live run 7: a hypothesis naming a decorator was refused as an email.
DECORATORS = [
    "`@app.route('/ping')` raised a 502 after the deploy",
    "the handler under @app.route('/ping') times out",
    "(@app.route) and '@cache.memoize' both wrap it",
]
STILL_EMAILS = [
    "jane@example.com",
    "jane＠example.com",
    "jane%40example.com",
    "jane&#64;example.com",
    "jane [at] example dot com",
    "jane​@example.com",
    "`jane@example.com`",
]


@pytest.mark.unit
@pytest.mark.parametrize("text", DECORATORS)
def test_a_decorator_is_not_an_email(text: str) -> None:
    _check_free_text(text, "Case.hypotheses[].statement")


@pytest.mark.unit
@pytest.mark.parametrize("text", STILL_EMAILS)
def test_emails_next_to_the_decorator_fix_are_still_rejected(text: str) -> None:
    with pytest.raises(ValueError, match="email"):
        _check_free_text(text, "Case.hypotheses[].statement")
