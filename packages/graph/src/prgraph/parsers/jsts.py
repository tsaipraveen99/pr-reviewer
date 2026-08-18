"""JavaScript/TypeScript source parser: extracts definitions into
prgraph.ir.FileIR.

Imports and calls are left empty for this task; they land in a follow-up
(js/ts import/call extraction).
"""

import tree_sitter_javascript
import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

from prgraph.ir import Def, FileIR

# Parser instances are expensive to construct, so cache one per grammar.
_PARSERS: dict[str, Parser] = {}

_VALUE_DEF_NODE_TYPES = ("arrow_function", "function_expression")


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


def parse_jsts(relpath: str, source: bytes, lang: str) -> FileIR:
    """Parse a JavaScript/TypeScript source file into a FileIR.

    Fills `module_qualified`, `defs` (module symbol first, then every
    function/class/method definition in document order). `imports` and
    `calls` are empty for this task; they're extracted in a follow-up.

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

    return FileIR(
        path=relpath,
        lang=lang,
        module_qualified=module,
        defs=defs,
        imports=[],
        calls=[],
    )
