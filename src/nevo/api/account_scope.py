"""The route guard: which kind of account may reach which route.

/me, Phase 0, ruling B (Lydia, 24 November 2026).

There are some two hundred places in this backend that resolve something by
matching on a school. For an account with no school every one of them returns
nothing rather than failing: ``school_id = NULL`` is neither true nor false in
SQL, so it matches no rows and the query succeeds. The learner sees an empty
page, the log shows a normal request, and nobody finds out. Triaging each
query is the version where three are missed, so the guard goes here, at the
route, once.

The rule fails closed:

* Every authenticated route is **school-only** unless it is listed below.
  An individual (/me) account reaching one is refused here, loudly, before the
  handler or any query runs.
* Every route under ``/api/v1/me`` is **individual-only**. A school account
  reaching one is refused the same way.
* A route that must work for both kinds is opened explicitly in
  ``SHARED_ROUTES``, and only after its school lookups have been read and made
  to work without a school. Adding a route there is the act of declaring it
  swept; do not add one to make a test pass.

A school account whose learner has no school (a broken roster row) is refused
on a school-only route too, rather than being handed the empty answers the
NULL comparison would give it.
"""

from __future__ import annotations

from enum import StrEnum

from fastapi import HTTPException, Request, status

from nevo.auth.entities import AuthPrincipal

API_PREFIX = "/api/v1"
INDIVIDUAL_PREFIX = f"{API_PREFIX}/me"


class AccountType(StrEnum):
    SCHOOL = "school"
    INDIVIDUAL = "individual"


class RouteAudience(StrEnum):
    SCHOOL_ONLY = "school_only"
    INDIVIDUAL_ONLY = "individual_only"
    SHARED = "shared"


#: Routes both kinds of account may reach, as (METHOD, path template).
#:
#: Session housekeeping only, for now: an individual account has to be able
#: to read its own session, keep it alive and end it. The 38 learner-surface
#: lookups (dashboard, lessons, onboarding, uploads, mastery) join this list
#: one by one as Phases 2, 3 and 5 make them work without a school.
SHARED_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", f"{API_PREFIX}/auth/session"),
        ("GET", f"{API_PREFIX}/auth/me"),
        ("POST", f"{API_PREFIX}/auth/session/refresh"),
        ("POST", f"{API_PREFIX}/auth/logout"),
    }
)


def is_individual_path(path: str) -> bool:
    return path == INDIVIDUAL_PREFIX or path.startswith(f"{INDIVIDUAL_PREFIX}/")


def audience_for(method: str, path: str) -> RouteAudience:
    """Classify a route by its path template (not the concrete URL)."""

    if (method.upper(), path) in SHARED_ROUTES:
        return RouteAudience.SHARED
    if is_individual_path(path):
        return RouteAudience.INDIVIDUAL_ONLY
    return RouteAudience.SCHOOL_ONLY


def _route_path(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    # The template, so /api/v1/students/{id} classifies the same for every id.
    # Fall back to the URL only if the router did not record a route.
    return path if isinstance(path, str) else request.url.path


def _refuse(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": code, "message": message},
    )


def enforce_account_scope(request: Request, principal: AuthPrincipal) -> None:
    """Refuse a principal whose account kind this route does not serve."""

    audience = audience_for(request.method, _route_path(request))
    if audience is RouteAudience.SHARED:
        return

    individual = principal.account_type == AccountType.INDIVIDUAL
    if audience is RouteAudience.INDIVIDUAL_ONLY:
        if not individual:
            raise _refuse(
                "individual_account_required",
                "This route serves individual accounts only.",
            )
        return

    # School-only from here.
    if individual:
        raise _refuse(
            "school_account_required",
            "This route serves school accounts only.",
        )
    if principal.role == "student" and principal.school_id is None:
        # A school learner with no school would get an empty answer from every
        # lookup on this route. Say so instead.
        raise _refuse(
            "school_scope_missing",
            "This account is not linked to a school.",
        )
