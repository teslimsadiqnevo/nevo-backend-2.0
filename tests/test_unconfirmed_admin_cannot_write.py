"""The unconfirmed-email write rule covers the scope-gated door too.

_refuse_unconfirmed_write says of itself that the rule covers every write in
the product, and that putting it on each handler is how the next handler
forgets. It was reached through require_school_actor, and scope-gated routes
do not go that way: they resolve a PermissionSnapshot straight from the
permission service.

So an administrator who had never proved their address could still write
through any scope-gated route. Billing contacts and payment methods are
where the console noticed it; the same door covers roster, curriculum,
oversight and IT work.
"""

from __future__ import annotations

import inspect

from nevo.api import permissions


def test_both_scope_dependencies_apply_the_rule() -> None:
    for dependency in (permissions.RequireScope, permissions.RequireAnyScope):
        source = inspect.getsource(dependency.__call__)
        assert "_refuse_an_unconfirmed_admin" in source, dependency.__name__


def test_the_rule_itself_is_not_copied() -> None:
    # One statement of the rule. The gate hands over the three facts and
    # defers to it rather than restating which roles it covers, which paths
    # are exempt, or what the refusal says, so the two doors cannot drift.
    gate = inspect.getsource(permissions._refuse_an_unconfirmed_admin)
    assert "refuse_unconfirmed_write(" in gate
    for restated in ("ADMIN_ROLES", "UNCONFIRMED_WRITE_ALLOWLIST", "email_not_confirmed"):
        assert restated not in gate


def test_the_gate_needs_no_database_session_of_its_own() -> None:
    # A route dependency resolves before the handler, so a second reason it
    # can fail is a second way a 403 the client earned comes back as a 503.
    # That has happened three times here. The snapshot already carries what
    # the rule needs.
    for dependency in (permissions.RequireScope, permissions.RequireAnyScope):
        signature = inspect.signature(dependency.__call__)
        assert "session" not in signature.parameters, dependency.__name__
    # The body, not the docstring, which explains why there is no session.
    body = inspect.getsource(permissions._refuse_an_unconfirmed_admin).split('"""')[-1]
    assert "session" not in body
    assert "await" not in body


def test_the_snapshot_defaults_to_confirmed() -> None:
    # A snapshot built without the field - a fake in a test, an older caller -
    # must not start refusing every write. The rule is applied to what the
    # repository actually read, and nothing else.
    from nevo.permissions.entities import PermissionSnapshot

    assert PermissionSnapshot.__dataclass_fields__["email_confirmed"].default is True
