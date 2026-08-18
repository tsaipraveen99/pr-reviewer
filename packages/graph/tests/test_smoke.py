import tree_sitter_python
from tree_sitter import Language, Parser

from prgraph import __version__


def test_version():
    """Test that prgraph has correct version."""
    assert __version__ == "0.1.0"


def test_tree_sitter_grammar_loads():
    """Test that tree-sitter grammar wheels load correctly."""
    parser = Parser(Language(tree_sitter_python.language()))
    assert parser is not None
