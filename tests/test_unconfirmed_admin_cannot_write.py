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
    # One statement of the rule. The gate here loads the user and defers to
    # it rather than restating which roles or paths are exempt, so the
    # allowlist and the role set cannot drift between the two doors.
    gate = inspect.getsource(permissions._refuse_an_unconfirmed_admin)
    assert "_refuse_unconfirmed_write(user)" in gate
    assert "ADMIN_ROLES" not in gate
    assert "email_confirmed_at" not in gate


def test_a_missing_user_is_not_treated_as_confirmed() -> None:
    # A principal whose row has gone is refused by the permission service on
    # the next line; this gate simply does not assert anything about them.
    gate = inspect.getsource(permissions._refuse_an_unconfirmed_admin)
    assert "if user is not None:" in gate


def test_the_gate_runs_before_the_scope_is_checked() -> None:
    # An unconfirmed admin gets "confirm your email", not "you lack the
    # billing scope", which is the more useful of the two and the one they
    # can act on.
    source = inspect.getsource(permissions.RequireScope.__call__)
    assert source.index("_refuse_an_unconfirmed_admin") < source.index("service.require")
