def test_overlong_call_target_is_clamped_to_column_width(tmp_path):
    """Postgres enforces VARCHAR(512); a giant unresolved JS callee expression
    must be clamped at store time, not crash the whole index run."""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from prgraph.db import Base, Edge
    from prgraph.indexer import index_repo

    root = tmp_path / "repo"
    root.mkdir()
    long_chain = "expect(" + "x.veryLongPropertyName" * 40 + ").toEqual"
    (root / "big.test.js").write_text(f"function t() {{ {long_chain}(1); }}\n")
    engine = create_engine(f"sqlite:///{tmp_path}/g.db")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    index_repo(factory, 1, root)
    with factory() as s:
        lengths = [len(e.dst_qualified_name) for e in s.execute(select(Edge)).scalars()]
    assert lengths and max(lengths) <= 512
