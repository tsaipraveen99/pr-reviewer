"""Tests for JS/TS definition extraction (prgraph.parsers.jsts)."""

from pathlib import Path

from prgraph.ir import Def
from prgraph.parsers.jsts import parse_jsts

FIXTURES = Path(__file__).parent / "fixtures" / "tsrepo"


def test_parse_jsts_api_defs():
    """src/api.ts: module symbol + function, arrow-function-as-const, class, method.

    Spans are hand-checked against the fixture source (tests/fixtures/tsrepo/src/api.ts,
    1-indexed line numbers) and against tree-sitter's actual node start_point/end_point
    for this exact fixture (verified via a one-off tree-sitter dump before freezing):
      - module symbol: whole file, lines 1-13 (13 lines total)
      - fetchUser (function_declaration, inside export_statement): lines 1-3
        (export_statement and function_declaration start on the same line here, so the
        wrapper contributes no span difference; we walk through export_statement without
        special-casing it, using the inner declaration node's own span)
      - listUsers (lexical_declaration whose declarator value is arrow_function): lines 5-7
        (span is the lexical_declaration's own start/end, which -- because `const` and the
        closing `};` line up with the arrow_function's own bounds in this fixture --
        equals the arrow_function's span too)
      - Client (class_declaration): lines 9-13
      - Client.get (method_definition, kind method, qualified src/api.Client.get): lines 10-12
    """
    source = (FIXTURES / "src" / "api.ts").read_bytes()
    ir = parse_jsts("src/api.ts", source, "typescript")

    assert ir.path == "src/api.ts"
    assert ir.lang == "typescript"
    assert ir.module_qualified == "src/api"
    assert ir.imports == []
    assert ir.calls == []

    assert ir.defs == [
        Def(
            name="api",
            qualified_name="src/api",
            kind="module",
            start_line=1,
            end_line=13,
        ),
        Def(
            name="fetchUser",
            qualified_name="src/api.fetchUser",
            kind="function",
            start_line=1,
            end_line=3,
        ),
        Def(
            name="listUsers",
            qualified_name="src/api.listUsers",
            kind="function",
            start_line=5,
            end_line=7,
        ),
        Def(
            name="Client",
            qualified_name="src/api.Client",
            kind="class",
            start_line=9,
            end_line=13,
        ),
        Def(
            name="get",
            qualified_name="src/api.Client.get",
            kind="method",
            start_line=10,
            end_line=12,
        ),
    ]


def test_parse_jsts_app_defs():
    """src/app.ts: module symbol + top-level function only.

    Spans hand-checked the same way as api.ts above:
      - module symbol: whole file, lines 1-6 (6 lines total)
      - main (function_declaration, inside export_statement): lines 3-6

    `const c = new Client();` is a lexical_declaration too, but its declarator's
    value is a `new_expression`, not arrow_function/function_expression -- it is
    NOT a def, exercising the exclusion path in _walk_lexical_declaration.
    """
    source = (FIXTURES / "src" / "app.ts").read_bytes()
    ir = parse_jsts("src/app.ts", source, "typescript")

    assert ir.module_qualified == "src/app"
    assert ir.imports == []
    assert ir.calls == []
    assert ir.defs == [
        Def(
            name="app",
            qualified_name="src/app",
            kind="module",
            start_line=1,
            end_line=6,
        ),
        Def(
            name="main",
            qualified_name="src/app.main",
            kind="function",
            start_line=3,
            end_line=6,
        ),
    ]


def test_parse_jsts_module_name_index_collapse():
    """src/util/index.ts collapses to module src/util (index segment dropped)."""
    source = b"export function helper() {\n  return 1;\n}\n"
    ir = parse_jsts("src/util/index.ts", source, "typescript")

    assert ir.module_qualified == "src/util"
    assert ir.defs[0] == Def(
        name="util", qualified_name="src/util", kind="module", start_line=1, end_line=3
    )
    assert ir.defs[1] == Def(
        name="helper",
        qualified_name="src/util.helper",
        kind="function",
        start_line=1,
        end_line=3,
    )
