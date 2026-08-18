"""Tests for Python import and call extraction (prgraph.parsers.python).

Expected import/call lists for tests/fixtures/pyrepo/main.py are the contract
frozen by task-5-brief.md and controller ruling R2:

    from pkg.models import User, helper as h
    import pkg.models

    def run():
        u = User()
        u.save()
        h()
        pkg.models.helper()

Imports:
  - `from pkg.models import User` -> Import("pkg.models", "pkg.models.User", "User")
  - `from pkg.models import helper as h` -> Import("pkg.models", "pkg.models.helper", "h")
  - `import pkg.models` (plain dotted import; R2: alias is the full dotted path,
    target_qualified == target_module == "pkg.models") ->
    Import("pkg.models", "pkg.models", "pkg.models")

Calls (all inside `run`, so caller_qualified == "main.run"):
  - `User()` -> bare name resolved via import alias -> "pkg.models.User"
  - `u.save()` -> dotted, no alias prefix matches "u" or "u.save" -> unresolved (None)
  - `h()` -> bare name resolved via import alias -> "pkg.models.helper"
  - `pkg.models.helper()` -> dotted, longest-prefix alias match on "pkg.models"
    (R2 rule 3) expanded with the remaining ".helper" -> "pkg.models.helper"
"""

from pathlib import Path

from prgraph.ir import Call, Import
from prgraph.parsers.python import parse_python

FIXTURES = Path(__file__).parent / "fixtures" / "pyrepo"


def _sort_key_import(imp: Import) -> tuple[str, str, str]:
    return (imp.alias, imp.target_qualified, imp.target_module or "")


def _sort_key_call(call: Call) -> tuple[str, str, str]:
    return (call.caller_qualified, call.callee_name, call.resolved_qualified or "")


def test_parse_python_main_imports_and_calls():
    """main.py imports + calls, exact list equality after sorting (frozen contract)."""
    source = (FIXTURES / "main.py").read_bytes()
    ir = parse_python("main.py", source)

    expected_imports = [
        Import("pkg.models", "pkg.models.User", "User"),
        Import("pkg.models", "pkg.models.helper", "h"),
        Import("pkg.models", "pkg.models", "pkg.models"),
    ]
    expected_calls = [
        Call(caller_qualified="main.run", callee_name="User", resolved_qualified="pkg.models.User"),
        Call(caller_qualified="main.run", callee_name="u.save", resolved_qualified=None),
        Call(caller_qualified="main.run", callee_name="h", resolved_qualified="pkg.models.helper"),
        Call(
            caller_qualified="main.run",
            callee_name="pkg.models.helper",
            resolved_qualified="pkg.models.helper",
        ),
    ]

    assert sorted(ir.imports, key=_sort_key_import) == sorted(expected_imports, key=_sort_key_import)
    assert sorted(ir.calls, key=_sort_key_call) == sorted(expected_calls, key=_sort_key_call)


def test_parse_python_decorator_calls_attribute_to_enclosing_scope():
    """Decorator expressions run in the ENCLOSING scope, not inside the def they decorate.

    `@app.route("/x")` on a module-level `handler` is a call made by the module itself
    (caller_qualified == module), resolved through the normal ladder like any other call
    (here: `app` is bound by `import app`, so the dotted callee `app.route` resolves via
    rule 3, longest-prefix alias match, to "app.route").

    `@property` on `Widget.label` has no explicit call syntax (no parens), but applying a
    decorator is itself an implicit call on the decorated function -- it must still be
    recorded, attributed to the enclosing class `Widget` (not to `label`). `property` is
    a builtin with no import or local def backing it, so it resolves to None.
    """
    source = b'''import app


@app.route("/x")
def handler():
    return 1


class Widget:
    @property
    def label(self):
        return "w"
'''
    ir = parse_python("svc.py", source)

    assert Call(
        caller_qualified="svc", callee_name="app.route", resolved_qualified="app.route"
    ) in ir.calls
    assert Call(
        caller_qualified="svc.Widget", callee_name="property", resolved_qualified=None
    ) in ir.calls
