"""Wires the nodes in app.agent.nodes into the LangGraph pipeline:

    generate_sql -> run_sql --(success)--> write_report -> END
                        ^  |
                        |  +--(failure, retries left)--> generate_sql
                        |
                        +--(failure, retries exhausted)--> give_up -> END
"""

from langgraph.graph import END, StateGraph

from app.agent.nodes import generate_sql, give_up, run_sql, should_retry, write_report
from app.agent.state import AgentState


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("generate_sql", generate_sql)
    graph.add_node("run_sql", run_sql)
    graph.add_node("write_report", write_report)
    graph.add_node("give_up", give_up)

    graph.set_entry_point("generate_sql")
    graph.add_edge("generate_sql", "run_sql")
    graph.add_conditional_edges(
        "run_sql",
        should_retry,
        {"retry": "generate_sql", "continue": "write_report", "give_up": "give_up"},
    )
    graph.add_edge("write_report", END)
    graph.add_edge("give_up", END)

    return graph.compile()
