"""Identity scrub for acquiring helper verbs (D3-24).

``drop_identity_fields`` removes SDK identity keys at any depth; ``redact_emails``
replaces every email-shaped substring with ``<email>``; ``scrub_identity`` does
both over a whole payload (keys dropped, every string value redacted).
"""

from __future__ import annotations

import pytest
from starboard_skills.helpers.contract import (
    drop_identity_fields,
    redact_emails,
    scrub_identity,
)


@pytest.mark.unit
class TestDropIdentityFields:
    def test_top_level_identity_keys_dropped(self):
        obj = {
            "query_id": "q1",
            "user_name": "a@b.com",
            "executed_as_user_name": "svc",
            "creator_user_name": "c",
            "run_as_user_name": "r",
            "owner_user_name": "o",
            "user_email": "x",
            "email_notifications": {"on_failure": ["a@b.com"]},
            "user_id": 7,
            "executed_as_user_id": 8,
            "duration": 12,
        }
        assert drop_identity_fields(obj) == {"query_id": "q1", "duration": 12}

    def test_nested_dicts_and_lists(self):
        obj = {
            "res": [
                {"query_id": "q1", "user_name": "u", "metrics": {"read_bytes": 5}},
                {"query_id": "q2", "nested": [{"owner_user_name": "o", "k": 1}]},
            ],
            "metadata": {
                "creator_user_name": "c",
                "state": {"life_cycle_state": "TERMINATED"},
            },
        }
        assert drop_identity_fields(obj) == {
            "res": [
                {"query_id": "q1", "metrics": {"read_bytes": 5}},
                {"query_id": "q2", "nested": [{"k": 1}]},
            ],
            "metadata": {"state": {"life_cycle_state": "TERMINATED"}},
        }

    def test_non_identity_lookalikes_kept(self):
        obj = {"username_hint": 1, "user_names_count": 2, "query_text": "SELECT 1"}
        assert drop_identity_fields(obj) == obj

    def test_input_not_mutated_and_scalars_pass_through(self):
        obj = {"user_name": "u", "a": [1, {"user_name": "v"}]}
        drop_identity_fields(obj)
        assert obj == {"user_name": "u", "a": [1, {"user_name": "v"}]}
        assert drop_identity_fields("x") == "x"
        assert drop_identity_fields(None) is None
        assert drop_identity_fields((1, {"user_name": "u"})) == [1, {}]


@pytest.mark.unit
class TestRedactEmails:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("WHERE owner = 'alice@corp.com'", "WHERE owner = '<email>'"),
            ("a@b.co and c.d+e@x.y.org", "<email> and <email>"),
            ("/Users/bob@acme.io/etl/nb", "/Users/<email>/etl/nb"),
            ("IN ('a@x.com','b@y.com')", "IN ('<email>','<email>')"),
            ('{"to": "ü.ser@exämple.de"}', '{"to": "<email>"}'),
            ("no address here @ all", "no address here @ all"),
            ("", ""),
        ],
    )
    def test_examples(self, text, expected):
        assert redact_emails(text) == expected

    def test_none_passes_through(self):
        assert redact_emails(None) is None

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("/Users/a%40x.com/nb", "/Users/<email>/nb"),
            ("/Users/JANE%40EXAMPLE.COM/nb", "/Users/<email>/nb"),
            ("jane@example.com%2Fnb", "<email>%2Fnb"),
            ("jane\uff20example.com", "<email>"),
            ("see /Users/jane\uff20example.com/x", "see /Users/<email>/x"),
        ],
    )
    def test_encoded_forms(self, text, expected):
        assert redact_emails(text) == expected

    def test_non_email_text_is_not_normalised(self):
        # NFKC is only applied when it reveals an address.
        assert redact_emails("\uff26ull 100% done @ 3pm") == "\uff26ull 100% done @ 3pm"


@pytest.mark.unit
class TestScrubIdentity:
    def test_drops_keys_and_redacts_every_string(self):
        obj = {
            "user_name": "u@x.com",
            "query_text": "SELECT 'u@x.com'",
            "rows": [["v@y.org", 1]],
            "metrics": {"read_bytes": 10},
        }
        assert scrub_identity(obj) == {
            "query_text": "SELECT '<email>'",
            "rows": [["<email>", 1]],
            "metrics": {"read_bytes": 10},
        }


@pytest.mark.unit
def test_redact_is_linear_on_long_runs_without_at():
    """A 1 MB @-free run (a log line) must not backtrack per start offset."""
    import time

    blob = "z" * 1_000_000 + " mail me: a@b.com"
    start = time.perf_counter()
    assert redact_emails(blob).endswith("mail me: <email>")
    assert time.perf_counter() - start < 1.0
