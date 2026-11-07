"""A transfer kind the compliance policy forbids cannot be generated at all.

SCRUM-295 renamed the fourth part from diagnosis to judgement, and the
rename turned out to be the reason transfer generation never worked rather
than a matter of wording.

The chain: the prompt instructed the model to return kind "diagnosis".
The gateway inspects every response against PROHIBITED_RESPONSE_TERMS,
which includes "diagnosis" - it sits alongside adhd, autism and disability,
banned so that nothing in this product labels a child. A violation is
retried with a rewrite instruction, and a kind is a required JSON value so
the retry says it too. After the retries the gateway falls back, and
generate_transfer_items turns a fallback into 503
transfer_generation_unavailable.

So the prompt asked for a word the safety layer is built to reject. The
policy existed, the kind escaped it because it lives in a JSON string
rather than a column name or an enum value, which is what the schema-term
contract checks.
"""

from __future__ import annotations

import inspect

from nevo.ai_gateway.compliance import PROHIBITED_RESPONSE_TERMS, ZeroTagCompliancePolicy
from nevo.api import lesson_review
from nevo.api.lesson_contracts import ComprehensionCheckpoint

TRANSFER_KINDS = ("application_a", "application_b", "comparison", "judgement")


def _kinds_in_the_validator() -> set[str]:
    source = inspect.getsource(lesson_review.generate_transfer_items)
    line = next(line for line in source.splitlines() if "kinds = {" in line)
    return {part.strip().strip('"') for part in line.split("{")[1].split("}")[0].split(",")}


def test_no_transfer_kind_is_a_prohibited_term() -> None:
    # The guard that was missing. A kind the compliance policy rejects makes
    # generation impossible, not merely badly named.
    for kind in TRANSFER_KINDS:
        assert kind not in PROHIBITED_RESPONSE_TERMS, kind


def test_a_generated_set_passes_the_compliance_policy() -> None:
    policy = ZeroTagCompliancePolicy()
    body = '{"items": [' + ", ".join(f'{{"kind": "{kind}"}}' for kind in TRANSFER_KINDS) + "]}"
    result = policy.inspect(body)
    assert result.allowed, sorted(result.violations)


def test_the_old_name_really_did_fail_the_policy() -> None:
    # Kept as evidence rather than trivia: this is why the button was held.
    assert not ZeroTagCompliancePolicy().inspect('{"kind": "diagnosis"}').allowed


def test_the_validator_and_the_contract_agree() -> None:
    # The validator requires all four kinds and rejects the set otherwise, so
    # a half-renamed system generates nothing.
    assert _kinds_in_the_validator() == set(TRANSFER_KINDS)
    field = ComprehensionCheckpoint.model_fields["transfer_kind"]
    rendered = str(field.annotation)
    for kind in TRANSFER_KINDS:
        assert kind in rendered, kind
    assert "diagnosis" not in rendered


def test_a_fallback_is_refused_rather_than_served() -> None:
    # Why a rejected response surfaced as a 503 rather than a weaker set: a
    # fallback-generated transfer item is not reviewed content.
    source = inspect.getsource(lesson_review.generate_transfer_items)
    assert "result.fallback_used" in source
    assert "transfer_generation_unavailable" in source
