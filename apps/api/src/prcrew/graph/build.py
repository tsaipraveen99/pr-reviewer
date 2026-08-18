from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from prcrew.graph.events import emit_from
from prcrew.graph.specialists import SPECIALISTS, make_specialist
from prcrew.graph.state import ReviewState
from prcrew.graph.synthesizer import make_synthesizer
from prcrew.graph.verifier import make_verifier
from prcrew.llm import AgentLLM


async def _intake(state: dict, config: RunnableConfig | None = None) -> dict:
    emit = emit_from(config)
    await emit({"type": "node_started", "node": "intake"})
    await emit({"type": "node_finished", "node": "intake"})
    return {}

def build_graph(specialist_llm: AgentLLM, synth_llm: AgentLLM):
    g = StateGraph(ReviewState)
    g.add_node("intake", _intake)
    for name in SPECIALISTS:
        g.add_node(name, make_specialist(name, specialist_llm))
    g.add_node("verifier", make_verifier(specialist_llm))
    g.add_node("synthesizer", make_synthesizer(synth_llm))

    g.add_edge(START, "intake")
    for name in SPECIALISTS:
        g.add_edge("intake", name)
    g.add_edge(list(SPECIALISTS), "verifier")  # join: waits for all four
    g.add_edge("verifier", "synthesizer")
    g.add_edge("synthesizer", END)
    return g.compile()
