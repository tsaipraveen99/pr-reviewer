"""Tests for Python definition extraction (prgraph.parsers.python)."""

from pathlib import Path

from prgraph.ir import Call, Def
from prgraph.parsers.python import parse_python

FIXTURES = Path(__file__).parent / "fixtures" / "pyrepo"


def test_parse_python_models_defs():
    """pkg/models.py: module symbol + class/method/decorated-method/function/nested-function.

    Spans are hand-checked against the fixture source (tests/fixtures/pyrepo/pkg/models.py,
    1-indexed line numbers) and against tree-sitter's actual node start_point/end_point for
    this exact fixture (verified via a one-off tree-sitter dump before freezing):
      - module symbol: whole file, lines 1-13 (13 lines total)
      - User (class_definition): lines 1-7 (class line through `label`'s closing body line)
      - save (function_definition, method): lines 2-3
      - label (decorated_definition -> function_definition, method): lines 5-7
        (start_line is the decorated_definition's start, i.e. the `@property` line, not the
        inner function_definition's own start line 6)
      - helper (function_definition, top-level function): lines 10-13
      - inner (function_definition, nested function): lines 11-12

    `ir.calls` is not empty: the `@property` decorator on `label` has no explicit call
    syntax (no parens), but applying a decorator is itself an implicit call on the
    decorated function. It's attributed to the enclosing scope (the `User` class, not
    `label` itself) and is unresolved (`property` is a builtin, not an import or local
    def in this module).
    """
    source = (FIXTURES / "pkg" / "models.py").read_bytes()
    ir = parse_python("pkg/models.py", source)

    assert ir.path == "pkg/models.py"
    assert ir.lang == "python"
    assert ir.module_qualified == "pkg.models"
    assert ir.imports == []
    assert ir.calls == [
        Call(
            caller_qualified="pkg.models.User",
            callee_name="property",
            resolved_qualified=None,
        ),
    ]

    assert ir.defs == [
        Def(
            name="models",
            qualified_name="pkg.models",
            kind="module",
            start_line=1,
            end_line=13,
        ),
        Def(
            name="User",
            qualified_name="pkg.models.User",
            kind="class",
            start_line=1,
            end_line=7,
        ),
        Def(
            name="save",
            qualified_name="pkg.models.User.save",
            kind="method",
            start_line=2,
            end_line=3,
        ),
        Def(
            name="label",
            qualified_name="pkg.models.User.label",
            kind="method",
            start_line=5,
            end_line=7,
        ),
        Def(
            name="helper",
            qualified_name="pkg.models.helper",
            kind="function",
            start_line=10,
            end_line=13,
        ),
        Def(
            name="inner",
            qualified_name="pkg.models.helper.inner",
            kind="function",
            start_line=11,
            end_line=12,
        ),
    ]


def test_parse_python_init_only_module_symbol():
    """pkg/__init__.py is empty: module name drops __init__, only the module Def is emitted.

    Empty file -> line count treated as 1 (no content lines), so the module symbol's span
    is 1-1 (hand-checked: splitlines() on b"" is [], and a defined span cannot have
    end_line < start_line, so an empty file's line count floors at 1).
    """
    source = (FIXTURES / "pkg" / "__init__.py").read_bytes()
    ir = parse_python("pkg/__init__.py", source)

    assert ir.module_qualified == "pkg"
    assert ir.imports == []
    assert ir.calls == []
    assert ir.defs == [
        Def(name="pkg", qualified_name="pkg", kind="module", start_line=1, end_line=1),
    ]


def test_parse_python_module_name_top_level():
    """Top-level main.py: module name is just `main` (no package prefix)."""
    source = (FIXTURES / "main.py").read_bytes()
    ir = parse_python("main.py", source)

    assert ir.module_qualified == "main"
    assert ir.defs[0] == Def(
        name="main", qualified_name="main", kind="module", start_line=1, end_line=9
    )
