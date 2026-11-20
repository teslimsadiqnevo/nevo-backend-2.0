"""Every annotation must resolve, because the container evaluates them.

20 November, three minutes of downtime. A helper was written with
`session: AsyncSession` and product_auth.py does not import AsyncSession.
It imported fine locally, the full suite passed, and the dyno crashed on
boot with NameError.

The reason is a Python version gap. Local is 3.14, where PEP 649 defers
annotation evaluation, so an undefined name in an annotation is never looked
up. The image is python:3.12-slim, which evaluates annotations eagerly at
function definition time - so the same code is a NameError there, at import,
which for a web process means the app never starts.

Nothing else in the suite could catch it: importing the module is exactly
what works locally. This forces every annotation to resolve, which is what
3.12 does on import anyway.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import typing

import pytest

import nevo

#: Modules that are expected to fail resolution for a reason of their own
#: rather than a mistake. Empty, deliberately: an entry here is a module the
#: image may refuse to import, so it wants a comment saying why.
EXPECTED_UNRESOLVED: frozenset[str] = frozenset()


def _modules() -> list[str]:
    found = []
    for module in pkgutil.walk_packages(nevo.__path__, prefix="nevo."):
        if module.ispkg:
            continue
        found.append(module.name)
    return sorted(found)


@pytest.mark.parametrize("module_name", _modules())
def test_annotations_resolve(module_name: str) -> None:
    if module_name in EXPECTED_UNRESOLVED:
        pytest.skip("declared as unresolvable, see EXPECTED_UNRESOLVED")
    try:
        module = importlib.import_module(module_name)
    except Exception as error:  # pragma: no cover - a broken import is its own bug
        pytest.fail(f"{module_name} does not import: {type(error).__name__}: {error}")

    unresolved: list[str] = []
    for name, value in vars(module).items():
        if getattr(value, "__module__", None) != module_name:
            continue
        if not (inspect.isfunction(value) or inspect.isclass(value)):
            continue
        try:
            typing.get_type_hints(value)
        except NameError as error:
            # The exact failure the image hits at import on 3.12.
            unresolved.append(f"{name}: {error}")
        except Exception:
            # A forward reference to something only a type checker sees is
            # not what this is looking for.
            continue
    assert not unresolved, (
        f"{module_name} has annotations that do not resolve. Python 3.12 in the "
        f"image evaluates these at import, so this is a crash on boot: "
        + "; ".join(unresolved)
    )
