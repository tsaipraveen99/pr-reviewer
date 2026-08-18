"""Intermediate Representation (IR) types for source code analysis."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Def:
    """Definition of a symbol (function, class, etc.) in source code.

    Attributes:
        name: The local name of the definition (e.g., "my_function")
        qualified_name: The fully qualified name (e.g., "module.submodule.my_function")
        kind: The kind of definition (e.g., "function", "class", "variable")
        start_line: 1-indexed line number where definition starts (inclusive)
        end_line: 1-indexed line number where definition ends (inclusive)
    """

    name: str
    qualified_name: str
    kind: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class Import:
    """Import statement in source code.

    Attributes:
        target_module: The resolved in-repo dotted module path (None if external)
        target_qualified: The fully qualified name being imported
        alias: The name it's bound to in this file's scope
    """

    target_module: str | None
    target_qualified: str
    alias: str


@dataclass(frozen=True)
class Call:
    """Function/method call in source code.

    Attributes:
        caller_qualified: The qualified name of the function making the call
        callee_name: The local name of the function being called
        resolved_qualified: The fully qualified name of the callee (None if unresolved)
    """

    caller_qualified: str
    callee_name: str
    resolved_qualified: str | None


@dataclass(frozen=True)
class FileIR:
    """Complete IR for a single source file.

    Attributes:
        path: Relative path to the file
        lang: Programming language (e.g., "python", "javascript")
        module_qualified: The fully qualified module name for this file
        defs: List of definitions found in this file
        imports: List of imports in this file
        calls: List of calls in this file
    """

    path: str
    lang: str
    module_qualified: str
    defs: list[Def]
    imports: list[Import]
    calls: list[Call]
