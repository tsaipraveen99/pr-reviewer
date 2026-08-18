"""JavaScript/TypeScript source parser: extracts definitions, imports, and
calls into prgraph.ir.FileIR.
"""

import posixpath

import tree_sitter_javascript
import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

from prgraph.ir import Call, Def, FileIR, Import

# Parser instances are expensive to construct, so cache one per grammar.
_PARSERS: dict[str, Parser] = {}

_VALUE_DEF_NODE_TYPES = ("arrow_function", "function_expression")
_SCOPE_DEF_NODE_TYPES = (
    "class_declaration",
    "function_declaration",
    "method_definition",
)
_CALLABLE_FUNC_NODE_TYPES = ("identifier", "member_expression")
_MODULE_EXTENSIONS = (".tsx", ".ts", ".jsx", ".js")


def _select_grammar(relpath: str, lang: str) -> tuple[str, object]:
    """Pick the tree-sitter grammar (cache key, language() callable) for this file.

    .tsx always gets the TSX grammar (JSX syntax inside TS), regardless of
    `lang`. Otherwise `lang == "typescript"` selects the plain TypeScript
    grammar (.ts); everything else (.js/.jsx) uses the JavaScript grammar,
    which already understands JSX syntax.
    """
    if relpath.endswith(".tsx"):
        return "tsx", tree_sitter_typescript.language_tsx
    if lang == "typescript":
        return "typescript", tree_sitter_typescript.language_typescript
    return "javascript", tree_sitter_javascript.language


def _get_parser(relpath: str, lang: str) -> Parser:
    """Return the module-level cached tree-sitter Parser for this file's grammar."""
    key, language_fn = _select_grammar(relpath, lang)
    parser = _PARSERS.get(key)
    if parser is None:
        parser = Parser(Language(language_fn()))
        _PARSERS[key] = parser
    return parser


def _module_name(relpath: str) -> str:
    """Compute the path-form module name for a repo-relative JS/TS file path.

    Extension is stripped (.ts/.tsx/.js/.jsx) and a trailing `/index` segment
    is collapsed into its parent directory:
      src/api.ts -> src/api; src/util/index.ts -> src/util.
    """
    stem = relpath
    for ext in (".tsx", ".ts", ".jsx", ".js"):
        if stem.endswith(ext):
            stem = stem[: -len(ext)]
            break
    return stem.removesuffix("/index")


def _line_count(source: bytes) -> int:
    """Line count for a file, floored at 1 (an empty file still spans line 1)."""
    return max(1, len(source.splitlines()))


def _text(node: Node) -> str:
    """Decode a tree-sitter node's exact source text."""
    assert node.text is not None
    return node.text.decode("utf-8")


def _qualify(module: str, ancestors: list[str], name: str) -> str:
    """Dotted-member qualification: module stays path-form, members join with '.'."""
    return ".".join([module, *ancestors, name])


def _walk(node: Node, ancestors: list[str], module: str, defs: list[Def]) -> None:
    """Recursively walk `node`'s children, appending Defs for nested definitions.

    `ancestors` is the stack of enclosing class/function names, used to build
    dotted qualified names (module.Class.method). `export`/`export default`
    wrappers (export_statement) aren't special-cased: they fall through to the
    generic recursion below, which finds the wrapped declaration directly.
    """
    for child in node.children:
        if child.type == "class_declaration":
            name = _text(child.child_by_field_name("name"))  # type: ignore[arg-type]
            defs.append(
                Def(
                    name=name,
                    qualified_name=_qualify(module, ancestors, name),
                    kind="class",
                    start_line=child.start_point[0] + 1,
                    end_line=child.end_point[0] + 1,
                )
            )
            _walk(child, [*ancestors, name], module, defs)
        elif child.type == "function_declaration":
            name = _text(child.child_by_field_name("name"))  # type: ignore[arg-type]
            defs.append(
                Def(
                    name=name,
                    qualified_name=_qualify(module, ancestors, name),
                    kind="function",
                    start_line=child.start_point[0] + 1,
                    end_line=child.end_point[0] + 1,
                )
            )
            _walk(child, [*ancestors, name], module, defs)
        elif child.type == "method_definition":
            name = _text(child.child_by_field_name("name"))  # type: ignore[arg-type]
            defs.append(
                Def(
                    name=name,
                    qualified_name=_qualify(module, ancestors, name),
                    kind="method",
                    start_line=child.start_point[0] + 1,
                    end_line=child.end_point[0] + 1,
                )
            )
            _walk(child, [*ancestors, name], module, defs)
        elif child.type == "lexical_declaration":
            _walk_lexical_declaration(child, ancestors, module, defs)
        else:
            _walk(child, ancestors, module, defs)


def _walk_lexical_declaration(
    node: Node, ancestors: list[str], module: str, defs: list[Def]
) -> None:
    """Emit a Def for each declarator in `node` whose value is a function.

    A `lexical_declaration` can carry multiple comma-separated declarators
    (`const a = ..., b = ...`); each one bound to an arrow_function or
    function_expression is its own def, named after the declarator (not the
    `const`/`let`/`var` statement). Declarators bound to anything else are
    skipped -- they're not defs.
    """
    for declarator in node.children:
        if declarator.type != "variable_declarator":
            continue
        value_node = declarator.child_by_field_name("value")
        if value_node is None or value_node.type not in _VALUE_DEF_NODE_TYPES:
            continue
        name = _text(declarator.child_by_field_name("name"))  # type: ignore[arg-type]
        defs.append(
            Def(
                name=name,
                qualified_name=_qualify(module, ancestors, name),
                kind="function",
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
            )
        )
        _walk(value_node, [*ancestors, name], module, defs)


def _string_value(node: Node) -> str:
    """Extract the literal value of a `string` node (strip the surrounding quotes)."""
    text = _text(node)
    if len(text) >= 2 and text[0] in "'\"" and text[-1] == text[0]:
        return text[1:-1]
    return text


def _resolve_specifier(relpath: str, specifier: str) -> str | None:
    """Resolve an import specifier to a path-form in-repo module, or None if not relative.

    Only specifiers starting with "./" or "../" are treated as relative (bare
    package specifiers, e.g. "some-pkg", are left unresolved). The specifier is
    normalized against the importing file's own directory, then a trailing
    known extension is stripped and a trailing `/index` segment is collapsed,
    mirroring `_module_name`.
    """
    if not specifier.startswith(("./", "../")):
        return None

    importer_dir = posixpath.dirname(relpath)
    joined = posixpath.normpath(posixpath.join(importer_dir, specifier))

    for ext in _MODULE_EXTENSIONS:
        if joined.endswith(ext):
            joined = joined[: -len(ext)]
            break
    return joined.removesuffix("/index")


def _target_qualified(
    base_module: str | None, specifier: str, exported_name: str | None
) -> str:
    """Compute an Import's target_qualified per the js/ts contract.

    Bare (non-relative) specifiers always use the raw specifier text, regardless
    of import form. Relative specifiers use the resolved module, plus the
    exported member name for named imports (module + "." + exportedName).
    """
    if base_module is None:
        return specifier
    if exported_name is not None:
        return f"{base_module}.{exported_name}"
    return base_module


def _add_import(dest: list[Import], alias_map: dict[str, Import], imp: Import) -> None:
    dest.append(imp)
    alias_map[imp.alias] = imp


def _collect_import_statement(
    node: Node, relpath: str, imports: list[Import], alias_map: dict[str, Import]
) -> None:
    """Collect bindings from one `import_statement` node.

    Side-effect-only imports (`import "./x"`, no import_clause) bind nothing
    and are skipped. Otherwise the clause is one of: a bare `identifier`
    (default import), a `namespace_import` (`* as ns`), a `named_imports`
    block (`{a, b as c}`), or a combination of a default identifier followed
    by a namespace/named clause (`import d, {a} from "./x"`) -- each binding
    child is handled independently.
    """
    source_node = node.child_by_field_name("source")
    clause = next((c for c in node.children if c.type == "import_clause"), None)
    if source_node is None or clause is None:
        return

    specifier = _string_value(source_node)
    base_module = _resolve_specifier(relpath, specifier)

    for child in clause.children:
        if child.type == "identifier":
            alias = _text(child)
            _add_import(
                imports,
                alias_map,
                Import(
                    target_module=base_module,
                    target_qualified=_target_qualified(base_module, specifier, None),
                    alias=alias,
                ),
            )
        elif child.type == "namespace_import":
            alias_node = next(
                (c for c in child.children if c.type == "identifier"), None
            )
            if alias_node is None:
                continue
            alias = _text(alias_node)
            _add_import(
                imports,
                alias_map,
                Import(
                    target_module=base_module,
                    target_qualified=_target_qualified(base_module, specifier, None),
                    alias=alias,
                ),
            )
        elif child.type == "named_imports":
            for spec in child.children:
                if spec.type != "import_specifier":
                    continue
                name_node = spec.child_by_field_name("name")
                if name_node is None:
                    continue
                alias_node = spec.child_by_field_name("alias")
                exported_name = _text(name_node)
                alias = _text(alias_node) if alias_node is not None else exported_name
                _add_import(
                    imports,
                    alias_map,
                    Import(
                        target_module=base_module,
                        target_qualified=_target_qualified(
                            base_module, specifier, exported_name
                        ),
                        alias=alias,
                    ),
                )


def _maybe_collect_require(
    node: Node, relpath: str, imports: list[Import], alias_map: dict[str, Import]
) -> None:
    """Collect a CommonJS `const m = require("./x")` binding, if `node` is one.

    Only the simple form -- a bare identifier bound directly to a `require(...)`
    call with a single string-literal argument -- is recognized; destructured
    requires (`const {a} = require("./x")`) are not handled (see module docstring
    gap notes / task report).
    """
    name_node = node.child_by_field_name("name")
    value_node = node.child_by_field_name("value")
    if name_node is None or value_node is None:
        return
    if name_node.type != "identifier" or value_node.type != "call_expression":
        return

    func_node = value_node.child_by_field_name("function")
    if (
        func_node is None
        or func_node.type != "identifier"
        or _text(func_node) != "require"
    ):
        return

    args_node = value_node.child_by_field_name("arguments")
    if args_node is None:
        return
    string_args = [c for c in args_node.children if c.type == "string"]
    if len(string_args) != 1:
        return

    specifier = _string_value(string_args[0])
    base_module = _resolve_specifier(relpath, specifier)
    alias = _text(name_node)
    _add_import(
        imports,
        alias_map,
        Import(
            target_module=base_module,
            target_qualified=_target_qualified(base_module, specifier, None),
            alias=alias,
        ),
    )


def _collect_imports(
    root: Node, relpath: str
) -> tuple[list[Import], dict[str, Import]]:
    """Collect every import/require binding in the file plus an alias -> Import lookup."""
    imports: list[Import] = []
    alias_map: dict[str, Import] = {}

    def visit(node: Node) -> None:
        if node.type == "import_statement":
            _collect_import_statement(node, relpath, imports, alias_map)
        elif node.type == "variable_declarator":
            _maybe_collect_require(node, relpath, imports, alias_map)
        for child in node.children:
            visit(child)

    visit(root)
    return imports, alias_map


def _resolve_call(
    callee_name: str, local_defs: set[str], alias_map: dict[str, Import], module: str
) -> str | None:
    """Resolve a call's callee_name to a fully qualified name, per the same
    resolution ladder as the Python parser (prgraph.parsers.python._resolve_call):

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
        Call(
            caller_qualified=caller_qualified,
            callee_name=callee_name,
            resolved_qualified=resolved,
        )
    )


def _handle_call_like(
    func_node: Node | None,
    ancestors: list[str],
    module: str,
    calls: list[Call],
    local_defs: set[str],
    alias_map: dict[str, Import],
) -> None:
    """Record a Call for a `call_expression`'s function or `new_expression`'s constructor."""
    if func_node is not None and func_node.type in _CALLABLE_FUNC_NODE_TYPES:
        callee_name = _text(func_node)
        resolved = _resolve_call(callee_name, local_defs, alias_map, module)
    else:
        callee_name = _text(func_node) if func_node is not None else ""
        resolved = None
    _append_call(callee_name, resolved, ancestors, module, calls)


def _collect_calls(
    node: Node,
    ancestors: list[str],
    module: str,
    calls: list[Call],
    local_defs: set[str],
    alias_map: dict[str, Import],
) -> None:
    """Recursively collect every call/new-expression, attributing it to its enclosing def.

    `ancestors` is the stack of enclosing def names (module-level calls, with
    an empty stack, attribute to the module symbol itself). Scope-introducing
    nodes mirror `_walk`/`_walk_lexical_declaration` exactly, so a call's
    attribution always matches the qualified_name of the Def it's textually
    inside: class/function declarations and methods push their name; a
    lexical-declaration declarator only pushes a name when its value is an
    arrow_function/function_expression (i.e. is itself a Def) -- otherwise
    (e.g. `const c = new Client()`) the declarator's own calls stay in the
    enclosing scope.
    """
    for child in node.children:
        if child.type == "call_expression":
            _handle_call_like(
                child.child_by_field_name("function"),
                ancestors,
                module,
                calls,
                local_defs,
                alias_map,
            )
            _collect_calls(child, ancestors, module, calls, local_defs, alias_map)
        elif child.type == "new_expression":
            _handle_call_like(
                child.child_by_field_name("constructor"),
                ancestors,
                module,
                calls,
                local_defs,
                alias_map,
            )
            _collect_calls(child, ancestors, module, calls, local_defs, alias_map)
        elif child.type in _SCOPE_DEF_NODE_TYPES:
            name = _text(child.child_by_field_name("name"))  # type: ignore[arg-type]
            _collect_calls(
                child, [*ancestors, name], module, calls, local_defs, alias_map
            )
        elif child.type == "lexical_declaration":
            _collect_calls_lexical_declaration(
                child, ancestors, module, calls, local_defs, alias_map
            )
        else:
            _collect_calls(child, ancestors, module, calls, local_defs, alias_map)


def _collect_calls_lexical_declaration(
    node: Node,
    ancestors: list[str],
    module: str,
    calls: list[Call],
    local_defs: set[str],
    alias_map: dict[str, Import],
) -> None:
    """Same declarator-value branch as `_walk_lexical_declaration`, for call attribution."""
    for declarator in node.children:
        if declarator.type != "variable_declarator":
            continue
        value_node = declarator.child_by_field_name("value")
        if value_node is not None and value_node.type in _VALUE_DEF_NODE_TYPES:
            name = _text(declarator.child_by_field_name("name"))  # type: ignore[arg-type]
            _collect_calls(
                value_node, [*ancestors, name], module, calls, local_defs, alias_map
            )
        else:
            _collect_calls(declarator, ancestors, module, calls, local_defs, alias_map)


def parse_jsts(relpath: str, source: bytes, lang: str) -> FileIR:
    """Parse a JavaScript/TypeScript source file into a FileIR.

    Fills `module_qualified`, `defs` (module symbol first, then every
    function/class/method definition in document order), `imports`, and
    `calls`.

    Args:
        relpath: Repo-relative path to the file (forward slashes).
        source: Raw file bytes.
        lang: "javascript" or "typescript" (.tsx always gets the TSX grammar).

    Returns:
        FileIR for this file.
    """
    module = _module_name(relpath)
    module_symbol = module.rsplit("/", 1)[-1]

    defs: list[Def] = [
        Def(
            name=module_symbol,
            qualified_name=module,
            kind="module",
            start_line=1,
            end_line=_line_count(source),
        )
    ]

    tree = _get_parser(relpath, lang).parse(source)
    _walk(tree.root_node, [], module, defs)

    imports, alias_map = _collect_imports(tree.root_node, relpath)

    local_defs = {
        d.name
        for d in defs
        if d.kind != "module" and d.qualified_name == f"{module}.{d.name}"
    }
    calls: list[Call] = []
    _collect_calls(tree.root_node, [], module, calls, local_defs, alias_map)

    return FileIR(
        path=relpath,
        lang=lang,
        module_qualified=module,
        defs=defs,
        imports=imports,
        calls=calls,
    )
