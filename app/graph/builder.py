from langgraph.graph import END, START, StateGraph

from app.graph.nodes import GraphNodes
from app.graph.state import AssistantState


def build_assistant_graph(
    nodes: GraphNodes,
    verify_enabled: bool = False,
    data_enabled: bool = False,
):
    builder = StateGraph(AssistantState)

    builder.add_node("analyze", nodes.analyze)
    builder.add_node("retrieve", nodes.retrieve)
    builder.add_node("generate", nodes.generate)
    builder.add_node("abstain", nodes.abstain)
    builder.add_node("greet", nodes.greet)
    builder.add_node("data_unavailable", nodes.data_unavailable)
    builder.add_node("out_of_scope", nodes.out_of_scope)

    builder.add_edge(START, "analyze")

    routes = {
        "retrieve": "retrieve",
        "greet": "greet",
        "data_unavailable": "data_unavailable",
        "out_of_scope": "out_of_scope",
    }

    if data_enabled:
        routes["plan_data"] = "plan_data"
        routes["data_needs_auth"] = "data_needs_auth"

    builder.add_conditional_edges("analyze", nodes.route_intent, routes)

    builder.add_conditional_edges(
        "retrieve",
        nodes.route_evidence,
        {"generate": "generate", "abstain": "abstain"},
    )

    terminals = ["abstain", "greet", "data_unavailable", "out_of_scope"]

    if data_enabled:
        for name in [
            "plan_data", "execute_tool", "compose_data", "data_message",
            "data_clarify", "data_needs_auth", "propose_action", "data_clarify_action",
        ]:
            builder.add_node(name, getattr(nodes, name))

        builder.add_conditional_edges(
            "plan_data",
            nodes.route_plan,
            {
                "execute_tool": "execute_tool",
                "data_unavailable": "data_unavailable",
                "data_clarify": "data_clarify",
                "data_clarify_action": "data_clarify_action",
                "propose_action": "propose_action",
            },
        )
        builder.add_conditional_edges(
            "execute_tool",
            nodes.route_tool,
            {"compose_data": "compose_data", "data_message": "data_message"},
        )
        terminals.extend(
            ["compose_data", "data_message", "data_clarify", "data_needs_auth", "propose_action", "data_clarify_action"]
        )

    if verify_enabled:
        builder.add_node("verify", nodes.verify)
        builder.add_node("reject", nodes.reject)

        builder.add_conditional_edges(
            "generate",
            nodes.route_after_generate,
            {"verify": "verify", "done": END},
        )
        builder.add_conditional_edges(
            "verify",
            nodes.route_verification,
            {"accept": END, "reject": "reject"},
        )
        builder.add_edge("reject", END)
    else:
        terminals.append("generate")

    for terminal in terminals:
        builder.add_edge(terminal, END)

    return builder.compile()