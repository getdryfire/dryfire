"""SPIKE-004 — import resolution for `impl: pkg.mod:func` passthrough mocks.

Reference implementation. DF-211 adapts `resolve_impl()` into the spec-loading
path so a bad `impl:` is a *positioned spec error at validate time* — before any
API spend (Q2).

Two facts this file pins down:

- Resolution is `importlib.import_module(mod)` + `getattr(mod, func)`. Importing
  the module runs its top-level code. That is inherent to Python import, cannot be
  avoided, and is part of the security posture (see FINDINGS.md Q5).
- The colon form `pkg.mod:func` (not `pkg.mod.func`) is deliberate: it removes the
  ambiguity between a submodule and an attribute. It is the same form used by
  setuptools entry points and `uvicorn app:main`, so it is already familiar.
"""

from __future__ import annotations

import importlib
import os
import sys
from typing import Any, Callable


class ImplResolutionError(Exception):
    """Raised when `impl:` cannot be resolved to a callable. DF-211 catches this
    at validate time and renders it as a positioned spec error (exit 2), never a
    mid-run crash."""


def resolve_impl(target: str) -> Callable[[dict[str, Any]], Any]:
    """`"pkg.mod:func"` -> the callable. Raises ImplResolutionError with a message
    a user can act on. Import-time side effects run here (documented)."""
    if target.count(":") != 1:
        raise ImplResolutionError(
            f"impl {target!r} must be 'package.module:function' "
            f"(one colon separating the module path from the attribute)"
        )
    module_path, _, attr = target.partition(":")
    if not module_path or not attr:
        raise ImplResolutionError(
            f"impl {target!r} must name both a module and a function, "
            f"e.g. 'mytools.impls:create_ticket'"
        )

    _ensure_cwd_importable()

    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise ImplResolutionError(
            f"impl {target!r}: cannot import module {module_path!r} ({exc})"
        ) from exc

    try:
        func = getattr(module, attr)
    except AttributeError as exc:
        raise ImplResolutionError(
            f"impl {target!r}: module {module_path!r} has no attribute {attr!r}"
        ) from exc

    if not callable(func):
        raise ImplResolutionError(
            f"impl {target!r}: {module_path}.{attr} is not callable "
            f"(got {type(func).__name__})"
        )
    return func


def _ensure_cwd_importable() -> None:
    """A suite is run from the user's repo root; their impl module lives there and
    is usually not installed. Put the CWD on the path so `mytools:func` resolves
    the same way `python -c 'import mytools'` would from that directory."""
    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.insert(0, cwd)
