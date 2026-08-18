async def _noop(_event: dict) -> None:
    return None

def emit_from(config: dict):
    return (config or {}).get("configurable", {}).get("emit", _noop)
