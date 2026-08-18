"""Python source parser: extracts definitions, imports, and calls into
prgraph.ir.FileIR.
"""

import tree_sitter_python
from tree_sitter import Language, Node, Parser

from prgraph.ir import Call, Def, FileIR, Import

# Parser instances are expensive to construct, so cache one per language.
_PARSERS: dict[str, Parser] = {}

_DEF_NODE_TYPES = ("function_definition", "class_definition")
_CALLABLE_FUNC_NODE_TYPES = ("identifier", "attribute")


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


def _text(node: Node) -> str:
    """Decode a tree-sitter node's exact source text."""
    assert node.text is not None
    return node.text.decode("utf-8")


def _is_package(relpath: str) -> bool:
    """True if `relpath` is a package's __init__.py (its own dotted name is the package)."""
    return relpath.rsplit("/", 1)[-1] == "__init__.py"


def _resolve_from_module(module_name_node: Node, module: str, is_package: bool) -> str:
    """Resolve the `module_name` field of an import_from_statement to a dotted string.

    Absolute (`dotted_name`): the module text as written, e.g. "pkg.models".
    Relative (`relative_import`, e.g. ".", ".sib", ".."): levels are resolved
    against `module`'s package path, per controller ruling R2. Level 1 (".")
    is the importing file's own package (itself, if it's an __init__.py;
    otherwise its containing package). Each extra dot climbs one more level.
    """
    if module_name_node.type != "relative_import":
        return _text(module_name_node)

    text = _text(module_name_node)
    level = len(text) - len(text.lstrip("."))
    trailing = text[level:]

    bits = module.split(".") if module else []
    if not is_package and bits:
        bits = bits[:-1]

    cut = max(len(bits) - level + 1, 0)
    base = ".".join(bits[:cut])

    if not trailing:
        return base
    return f"{base}.{trailing}" if base else trailing


def _add_import(dest: list[Import], alias_map: dict[str, Import], imp: Import) -> None:
    dest.append(imp)
    alias_map[imp.alias] = imp


def _collect_imports(
    root: Node, module: str, is_package: bool
) -> tuple[list[Import], dict[str, Import]]:
    """Collect every import statement in the file plus an alias -> Import lookup."""
    imports: list[Import] = []
    alias_map: dict[str, Import] = {}

    def visit(node: Node) -> None:
        if node.type == "import_statement":
            for name_node in node.children_by_field_name("name"):
                if name_node.type == "aliased_import":
                    dotted = _text(name_node.child_by_field_name("name"))  # type: ignore[arg-type]
                    alias = _text(name_node.child_by_field_name("alias"))  # type: ignore[arg-type]
                else:
                    dotted = _text(name_node)
                    alias = dotted
                _add_import(
                    imports,
                    alias_map,
                    Import(target_module=dotted, target_qualified=dotted, alias=alias),
                )
        elif node.type == "import_from_statement":
            module_name_node = node.child_by_field_name("module_name")
            if module_name_node is not None:
                base_module = _resolve_from_module(module_name_node, module, is_package)
                for name_node in node.children_by_field_name("name"):
                    if name_node.type == "aliased_import":
                        src_name = _text(name_node.child_by_field_name("name"))  # type: ignore[arg-type]
                        alias = _text(name_node.child_by_field_name("alias"))  # type: ignore[arg-type]
                    else:
                        src_name = _text(name_node)
                        alias = src_name
                    target_qualified = (
                        f"{base_module}.{src_name}" if base_module else src_name
                    )
                    _add_import(
                        imports,
                        alias_map,
                        Import(
                            target_module=base_module,
                            target_qualified=target_qualified,
                            alias=alias,
                        ),
                    )
        for child in node.children:
            visit(child)

    visit(root)
    return imports, alias_map


def _resolve_call(
    callee_name: str, local_defs: set[str], alias_map: dict[str, Import], module: str
) -> str | None:
    """Resolve a call's callee_name to a fully qualified name, per the ladder in R2:

    (1) bare name matching a local (module-top-level) def -> "module.name"
    (2) bare name bound by an import alias -> that import's target_qualified
    (3) dotted name whose longest alias-matching prefix is an import alias ->
        that alias's target_qualified with the remaining dotted suffix appended
    (4) else unresolved (None)
    """
    if "." not in callee_name:
        if callee_name in local_defs:
            return f"{module}.{callee_name}"
        imp = alias_map.get(callee_name)
        return imp.target_qualified if imp is not None else None

    parts = callee_name.split(".")
    for i in range(len(parts), 0, -1):
        prefix = ".".join(parts[:i])
        imp = alias_map.get(prefix)
        if imp is not None:
            remainder = parts[i:]
            if not remainder:
                return imp.target_qualified
            return imp.target_qualified + "." + ".".join(remainder)
    return None


def _append_call(
    callee_name: str,
    resolved: str | None,
    ancestors: list[str],
    module: str,
    calls: list[Call],
) -> None:
    """Append a Call for `callee_name`, caller-qualified from `ancestors`/`module`."""
    caller_qualified = ".".join([module, *ancestors]) if ancestors else module
    calls.append(
        Call(caller_qualified=caller_qualified, callee_name=callee_name, resolved_qualified=resolved)
    )


def _collect_calls(
    node: Node,
    ancestors: list[str],
    module: str,
    calls: list[Call],
    local_defs: set[str],
    alias_map: dict[str, Import],
) -> None:
    """Recursively collect every `call` node, attributing it to its enclosing def.

    `ancestors` is the stack of enclosing def names (module-level calls, with
    an empty stack, attribute to the module symbol itself). Decorator expressions
    run in the ENCLOSING scope, not inside the function/class they decorate, so
    calls found there -- including bare-name/attribute decorators like `@property`,
    which apply the decorator as an implicit call with no explicit call syntax --
    are attributed to `ancestors`, not `[*ancestors, name]`.
    """
    for child in node.children:
        if child.type == "call":
            func_node = child.child_by_field_name("function")
            if func_node is not None and func_node.type in _CALLABLE_FUNC_NODE_TYPES:
                callee_name = _text(func_node)
                resolved = _resolve_call(callee_name, local_defs, alias_map, module)
            else:
                callee_name = _text(func_node) if func_node is not None else ""
                resolved = None
            _append_call(callee_name, resolved, ancestors, module, calls)
            _collect_calls(child, ancestors, module, calls, local_defs, alias_map)
        elif child.type == "decorated_definition":
            inner = next(c for c in child.children if c.type in _DEF_NODE_TYPES)
            for deco in child.children:
                if deco.type != "decorator":
                    continue
                expr = next((c for c in deco.children if c.type != "@"), None)
                if expr is None:
                    continue
                if expr.type in _CALLABLE_FUNC_NODE_TYPES:
                    # Bare name/attribute decorator (e.g. `@property`, `@a.b`):
                    # no explicit call syntax, but applying it IS an implicit
                    # call on the decorated function -- there's no `call` node
                    # for the generic scan below to find, so record it directly.
                    callee_name = _text(expr)
                    resolved = _resolve_call(callee_name, local_defs, alias_map, module)
                    _append_call(callee_name, resolved, ancestors, module, calls)
                else:
                    # `@app.route("/foo")` etc: the decorator's expression is
                    # itself a `call` node (or something stranger); the generic
                    # scan below picks it up, still in the enclosing scope.
                    _collect_calls(deco, ancestors, module, calls, local_defs, alias_map)
            name_node = inner.child_by_field_name("name")
            name = _text(name_node) if name_node is not None else ""
            _collect_calls(inner, [*ancestors, name], module, calls, local_defs, alias_map)
        elif child.type in _DEF_NODE_TYPES:
            name_node = child.child_by_field_name("name")
            name = _text(name_node) if name_node is not None else ""
            _collect_calls(child, [*ancestors, name], module, calls, local_defs, alias_map)
        else:
            _collect_calls(child, ancestors, module, calls, local_defs, alias_map)


def parse_python(relpath: str, source: bytes) -> FileIR:
    """Parse a Python source file into a FileIR.

    Fills `module_qualified`, `defs` (module symbol first, then every
    function/class definition in document order), `imports`, and `calls`.

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

    imports, alias_map = _collect_imports(tree.root_node, module, _is_package(relpath))

    local_defs = {
        d.name for d in defs if d.kind != "module" and d.qualified_name == f"{module}.{d.name}"
    }
    calls: list[Call] = []
    _collect_calls(tree.root_node, [], module, calls, local_defs, alias_map)

    return FileIR(
        path=relpath,
        lang="python",
        module_qualified=module,
        defs=defs,
        imports=imports,
        calls=calls,
    )
