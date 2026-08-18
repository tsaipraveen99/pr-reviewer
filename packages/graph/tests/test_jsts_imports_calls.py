"""Tests for JS/TS import and call extraction (prgraph.parsers.jsts).

Expected import/call lists for tests/fixtures/tsrepo/src/app.ts are the contract
frozen by task-7-brief.md:

    import { fetchUser, Client } from "./api";
    const c = new Client();
    export function main() {
      fetchUser("1");
      c.get("/");
    }

Imports (both named, both from the relative specifier "./api", which resolves
against app.ts's own directory "src" to the path-form module "src/api"):
  - `fetchUser` -> Import("src/api", "src/api.fetchUser", "fetchUser")
  - `Client` -> Import("src/api", "src/api.Client", "Client")

Calls:
  - `new Client()` at module top level -> caller is the module symbol itself
    ("src/app"); "Client" is a bare name bound by the import alias -> resolves
    to "src/api.Client".
  - `fetchUser("1")` inside `main` -> caller "src/app.main"; bare name bound
    by the import alias -> resolves to "src/api.fetchUser".
  - `c.get("/")` inside `main` -> caller "src/app.main"; dotted callee, no
    alias matches "c" or "c.get" (the receiver "c" is a local variable, not an
    import) -> unresolved (None), full dotted text kept as callee_name.
"""

from pathlib import Path

from prgraph.ir import Call, Import
from prgraph.parsers.jsts import parse_jsts

FIXTURES = Path(__file__).parent / "fixtures" / "tsrepo"


def _sort_key_import(imp: Import) -> tuple[str, str, str]:
    return (imp.alias, imp.target_qualified, imp.target_module or "")


def _sort_key_call(call: Call) -> tuple[str, str, str]:
    return (call.caller_qualified, call.callee_name, call.resolved_qualified or "")


def test_parse_jsts_app_imports_and_calls():
    """src/app.ts imports + calls, exact list equality after sorting (frozen contract)."""
    source = (FIXTURES / "src" / "app.ts").read_bytes()
    ir = parse_jsts("src/app.ts", source, "typescript")

    expected_imports = [
        Import("src/api", "src/api.fetchUser", "fetchUser"),
        Import("src/api", "src/api.Client", "Client"),
    ]
    expected_calls = [
        Call(
            caller_qualified="src/app",
            callee_name="Client",
            resolved_qualified="src/api.Client",
        ),
        Call(
            caller_qualified="src/app.main",
            callee_name="fetchUser",
            resolved_qualified="src/api.fetchUser",
        ),
        Call(
            caller_qualified="src/app.main",
            callee_name="c.get",
            resolved_qualified=None,
        ),
    ]

    assert sorted(ir.imports, key=_sort_key_import) == sorted(
        expected_imports, key=_sort_key_import
    )
    assert sorted(ir.calls, key=_sort_key_call) == sorted(
        expected_calls, key=_sort_key_call
    )


def test_parse_jsts_bare_specifier_import_unresolved():
    """A bare package specifier does not resolve to an in-repo module.

    `import pkg from "some-pkg"` -> target_module is None, target_qualified
    is the raw specifier text (no path-form resolution attempted), alias is
    the local binding name.
    """
    source = b'import pkg from "some-pkg";\n'
    ir = parse_jsts("src/thing.ts", source, "typescript")

    assert ir.imports == [
        Import(target_module=None, target_qualified="some-pkg", alias="pkg")
    ]


def test_parse_jsts_namespace_import_and_dotted_call():
    """`import * as ns from "./x"` binds `ns`; `ns.fetchUser()` resolves via the
    longest dotted-prefix alias match (ladder rule 3), appending the remaining
    suffix to the namespace import's target_qualified.
    """
    source = b'import * as ns from "./x";\nns.fetchUser();\n'
    ir = parse_jsts("src/thing.ts", source, "typescript")

    assert ir.imports == [
        Import(target_module="src/x", target_qualified="src/x", alias="ns")
    ]
    assert (
        Call(
            caller_qualified="src/thing",
            callee_name="ns.fetchUser",
            resolved_qualified="src/x.fetchUser",
        )
        in ir.calls
    )


def test_parse_jsts_require_binds_alias():
    """`const m = require("./x")` is a CommonJS import: target_qualified equals
    the resolved module (same rule as default/namespace imports), alias is the
    declared variable name.
    """
    source = b'const m = require("./x");\n'
    ir = parse_jsts("src/thing.ts", source, "typescript")

    assert ir.imports == [
        Import(target_module="src/x", target_qualified="src/x", alias="m")
    ]
