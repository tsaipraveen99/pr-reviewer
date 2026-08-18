"""Python source parser: extracts definitions into prgraph.ir.FileIR.

Imports and calls are filled in by a later task; this module always returns
empty lists for FileIR.imports and FileIR.calls.
"""

import tree_sitter_python
from tree_sitter import Language, Node, Parser

from prgraph.ir import Def, FileIR

# Parser instances are expensive to construct, so cache one per language.
_PARSERS: dict[str, Parser] = {}

_DEF_NODE_TYPES = ("function_definition", "class_definition")


def _get_parser() -> Parser:
    """Return the module-level cached tree-sitter Parser for Python."""
    parser = _PARSERS.get("python")
    if parser is None:
        parser = Parser(Language(tree_sitter_python.language()))
        _PARSERS["python"] = parser
    return parser


def _module_name(relpath: str) -> str:
    """Compute the dotted module name for a repo-relative Python file path.

    pkg/mod.py -> pkg.mod; pkg/__init__.py -> pkg; top-level main.py -> main.
    """
    parts = relpath.split("/")
    stem = parts[-1].removesuffix(".py")
    package_parts = parts[:-1]
    if stem == "__init__":
        dotted_parts = package_parts
    else:
        dotted_parts = [*package_parts, stem]
    return ".".join(dotted_parts)


def _line_count(source: bytes) -> int:
    """Line count for a file, floored at 1 (an empty file still spans line 1)."""
    return max(1, len(source.splitlines()))


def _walk(
    node: Node, ancestors: list[tuple[str, bool]], module: str, defs: list[Def]
) -> None:
    """Recursively walk `node`'s children, appending Defs for nested definitions.

    `ancestors` is the stack of (name, is_class) for enclosing class/function
    definitions, used both for dotted qualification and for method-vs-function
    classification (nearest def-ancestor is a class -> method).
    """
    for child in node.children:
        if child.type == "decorated_definition":
            inner = next(c for c in child.children if c.type in _DEF_NODE_TYPES)
            _emit(inner, ancestors, module, defs, start_line=child.start_point[0] + 1)
        elif child.type in _DEF_NODE_TYPES:
            _emit(child, ancestors, module, defs, start_line=child.start_point[0] + 1)
        else:
            _walk(child, ancestors, module, defs)


def _emit(
    node: Node,
    ancestors: list[tuple[str, bool]],
    module: str,
    defs: list[Def],
    start_line: int,
) -> None:
    """Append the Def for `node` (function_definition or class_definition), then recurse."""
    name_node = node.child_by_field_name("name")
    assert name_node is not None and name_node.text is not None
    name = name_node.text.decode("utf-8")

    is_class = node.type == "class_definition"
    if is_class:
        kind = "class"
    elif ancestors and ancestors[-1][1]:
        kind = "method"
    else:
        kind = "function"

    qualified_name = ".".join([module, *(a[0] for a in ancestors), name])
    end_line = node.end_point[0] + 1
    defs.append(
        Def(
            name=name,
            qualified_name=qualified_name,
            kind=kind,
            start_line=start_line,
            end_line=end_line,
        )
    )

    _walk(node, [*ancestors, (name, is_class)], module, defs)


def parse_python(relpath: str, source: bytes) -> FileIR:
    """Parse a Python source file into a FileIR.

    Fills `module_qualified` and `defs` (module symbol first, then every
    function/class definition in document order). `imports` and `calls` are
    always empty here; a later task fills them in.

    Args:
        relpath: Repo-relative path to the file (forward slashes).
        source: Raw file bytes.

    Returns:
        FileIR for this file.
    """
    module = _module_name(relpath)
    module_symbol = module.rsplit(".", 1)[-1]

    defs: list[Def] = [
        Def(
            name=module_symbol,
            qualified_name=module,
            kind="module",
            start_line=1,
            end_line=_line_count(source),
        )
    ]

    tree = _get_parser().parse(source)
    _walk(tree.root_node, [], module, defs)

    return FileIR(
        path=relpath,
        lang="python",
        module_qualified=module,
        defs=defs,
        imports=[],
        calls=[],
    )
