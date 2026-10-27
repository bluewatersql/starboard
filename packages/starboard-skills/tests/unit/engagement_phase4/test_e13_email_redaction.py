"""E13 Email redaction (spec §H.13, D4-11).

``starboard_x.diagnostic.query_profile`` uses the strong
``starboard_x.contract.redact_emails``: its local ``_EMAIL`` and
``redact_emails`` are gone, and ``parse_profile`` redacts plain, ``%40``,
fullwidth ``＠`` and quoted forms in ``queryText`` to ``<email>``. The heavy
``QueryProfileExplorer`` wrapper's output carries no email either.

Every address is built by concatenation, so no email literal is in this file.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from ._support import EMAIL_RE

PLACEHOLDER = "<email>"
LOCAL, DOMAIN = "alice", "example.com"
FORMS = {
    "plain": LOCAL + "@" + DOMAIN,
    "percent": LOCAL + "%40" + DOMAIN,
    "fullwidth": LOCAL + "＠" + DOMAIN,
}
#: queryText -> the redacted text that must appear in the parsed ``queryText``.
QUERIES = {
    "plain": (
        f"SELECT * FROM t WHERE owner = {FORMS['plain']}",
        f"owner = {PLACEHOLDER}",
    ),
    "percent": (
        f"SELECT * FROM t WHERE ref = {FORMS['percent']}",
        f"ref = {PLACEHOLDER}",
    ),
    "fullwidth": (
        f"SELECT * FROM t WHERE owner = {FORMS['fullwidth']}",
        f"owner = {PLACEHOLDER}",
    ),
    "single_quoted": (
        f"SELECT * FROM t WHERE owner = '{FORMS['plain']}'",
        f"owner = '{PLACEHOLDER}'",
    ),
    "double_quoted": (
        f'SELECT * FROM t WHERE owner = "{FORMS["plain"]}"',
        f'owner = "{PLACEHOLDER}"',
    ),
}


def _profile(query_text: str) -> str:
    """A minimal Liquid profile whose ``query.queryText`` is ``query_text``."""
    return json.dumps(
        {
            "graphs": [
                {
                    "nodes": [
                        {
                            "id": "1",
                            "name": "Scan parquet t",
                            "tag": "FileScan",
                            "metrics": [],
                        },
                        {
                            "id": "2",
                            "name": "SortMergeJoin",
                            "tag": "SortMergeJoin",
                            "metrics": [],
                        },
                    ],
                    "edges": [],
                }
            ],
            "query": {
                "id": "q-e13",
                "status": "FINISHED",
                "queryText": query_text,
                "metrics": {"totalTimeMs": 1000},
            },
        }
    )


def _leaks(obj: Any) -> list[str]:
    text = obj if isinstance(obj, str) else json.dumps(obj, default=str)
    hits = EMAIL_RE.findall(text)
    return hits + [f for f in FORMS.values() if f in text]


def test_query_profile_has_no_local_email_redactor() -> None:
    from starboard_x.diagnostic import query_profile

    assert not hasattr(query_profile, "_EMAIL")
    assert not hasattr(query_profile, "redact_emails")
    assert "redact_emails" not in getattr(query_profile, "__all__", ())


@pytest.mark.parametrize("form", sorted(QUERIES))
def test_parse_profile_redacts_every_email_form(form: str) -> None:
    from starboard_x.diagnostic.query_profile import parse_profile

    query_text, expected = QUERIES[form]
    summary = parse_profile(_profile(query_text))
    redacted = summary.query.get("queryText")
    assert isinstance(redacted, str)
    assert expected in redacted, redacted
    assert _leaks(redacted) == []
    assert _leaks(summary.to_dict()) == []


@pytest.mark.parametrize("form", sorted(QUERIES))
def test_the_heavy_wrapper_output_has_no_email(form: str) -> None:
    from starboard.tools.domain.diagnostic.query_profile_explorer import (
        QueryProfileExplorer,
    )

    query_text, _expected = QUERIES[form]
    result = QueryProfileExplorer().explore(
        _profile(query_text), "overview of the query text and joins", "exhaustive"
    )
    assert _leaks(result.content) == []
    assert _leaks(repr(result)) == []
