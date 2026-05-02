"""LangGraph Agent 核心。

构建一个最小但完整的 ReAct 风格状态图：
    START → agent (LLM 判断是否需要调工具)
    agent → tools (执行工具)
    tools → agent (循环直到 LLM 输出最终答案)
    agent → END

通过 SQLite 持久化对话上下文，保证多轮可接续。
"""
from __future__ import annotations

import logging
from typing import Annotated, List, TypedDict

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from . import db, tools as tools_mod
from .config import LLM_CONF

log = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "你是智能云边端调度系统的运维助手，可以通过工具直接调用 Kubernetes API。"
    "你必须用工具完成实际操作，不要凭空编造结果。"
    "面对自然语言指令，先把需求拆分为以下参数，再选择合适的工具调用：\n"
    "- 动作：创建/列出/删除/执行代码/查看节点等\n"
    "- 架构（arch）：amd64/arm64/riscv64 等（riscv=riscv64，arm=arm64，x86/x86_64=amd64）\n"
    "- 节点类型（node_type）：cloud（云节点）/ edge（边缘节点）/ device（端设备）\n"
    "  集群节点通过 node-type 标签区分：kubectl label nodes <name> node-type=cloud/edge/device\n"
    "  未打标签的节点默认视为 edge\n"
    "- hostname：固定调度到指定节点（主机名）\n"
    "- image：容器镜像，如 ubuntu:20.04 或 docker.io/library/ubuntu:20.04\n"
    "arch 与 node_type 可同时指定（取交集），hostname 优先级最高。"
    "所有参数均有默认值，不需要用户补充也能执行。"
    "如果用户上传了 Python 代码并要求执行，请使用 run_uploaded_python 工具。"
    "管理员才可以查看/删除集群节点。所有回答使用简体中文。"
)


class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]


_GRAPH_CACHE = {}


def _make_llm():
    return ChatOpenAI(
        base_url=LLM_CONF.get("api_base"),
        api_key=LLM_CONF.get("api_key"),
        model=LLM_CONF.get("model", "gpt-4o-mini"),
        temperature=float(LLM_CONF.get("temperature", 0.2)),
    )


def _build_graph(user: dict):
    """根据用户角色绑定不同工具集。缓存 by role，避免重复构建。"""
    role = user.get("role", "user")
    if role in _GRAPH_CACHE:
        return _GRAPH_CACHE[role]

    available_tools = tools_mod.tools_for(user)
    llm = _make_llm().bind_tools(available_tools)
    tool_node = ToolNode(available_tools)

    def call_model(state: AgentState):
        msgs = state["messages"]
        # 注入 system
        if not msgs or not isinstance(msgs[0], SystemMessage):
            msgs = [SystemMessage(content=SYSTEM_PROMPT)] + msgs
        ai = llm.invoke(msgs)
        return {"messages": [ai]}

    def should_continue(state: AgentState):
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
            return "tools"
        return END

    g = StateGraph(AgentState)
    g.add_node("agent", call_model)
    g.add_node("tools", tool_node)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")
    compiled = g.compile()
    _GRAPH_CACHE[role] = compiled
    return compiled


def _history_to_messages(rows) -> list[BaseMessage]:
    out: list[BaseMessage] = []
    for r in rows:
        if r["role"] == "user":
            out.append(HumanMessage(content=r["content"]))
        elif r["role"] == "assistant":
            out.append(AIMessage(content=r["content"]))
        elif r["role"] == "system":
            out.append(SystemMessage(content=r["content"]))
    return out


def chat(user: dict, user_text: str, uploaded_file: str | None = None) -> str:
    """单次对话入口：把历史 + 当前消息丢进 graph，得到最终回复。"""
    tools_mod.set_user(user, uploaded_file=uploaded_file)
    db.add_chat(user["id"], "user", user_text)

    history = db.get_chat(user["id"], limit=20)
    msgs = _history_to_messages(history[:-1])  # 不重复包含刚刚加进去的当前消息
    msgs.append(HumanMessage(content=user_text))

    api_key = LLM_CONF.get("api_key", "")
    if not api_key or api_key.startswith("sk-REPLACE"):
        # LLM 未配置 → 退化到规则解析
        reply = _fallback_chat(user, user_text, uploaded_file)
        db.add_chat(user["id"], "assistant", reply)
        return reply

    try:
        graph = _build_graph(user)
        result = graph.invoke({"messages": msgs})
        final = result["messages"][-1]
        reply = final.content if isinstance(final.content, str) else str(final.content)
    except Exception as e:
        log.exception("Agent 调用失败")
        reply = f"⚠️ Agent 调用失败：{e}\n已退化为规则解析：\n" + _fallback_chat(user, user_text, uploaded_file)

    db.add_chat(user["id"], "assistant", reply)
    return reply


def _fallback_chat(user: dict, text: str, uploaded_file: str | None) -> str:
    """LLM 不可用时的兜底执行路径，仅覆盖核心动作。"""
    parsed = tools_mod.fallback_parse(text)
    if not parsed:
        return (
            "（未配置 LLM，规则解析未识别该指令）\n"
            "示例：\n"
            "- 创建一个 riscv 架构的 Ubuntu SSH 容器\n"
            "- 在 hostname 为 arm202 的节点上创建 2 个 arm64 容器\n"
            "- 列出我的资源\n"
            "- 删除 <pod-name>\n"
            "- 在 arm202 节点上执行这份 Python 代码"
        )
    action = parsed["action"]
    if action == "create_ssh":
        return tools_mod.create_ssh_container.invoke({
            "arch": parsed.get("arch"),
            "hostname": parsed.get("hostname"),
            "image": parsed.get("image"),
            "count": parsed.get("count", 1),
            "node_type": parsed.get("node_type"),
        })
    if action == "list":
        return tools_mod.list_my_resources.invoke({})
    if action == "delete":
        if not parsed.get("pod_name"):
            return "请提供要删除的 Pod 名称"
        return tools_mod.delete_my_pod.invoke({"pod_name": parsed["pod_name"]})
    if action == "nodes":
        return tools_mod.admin_list_nodes.invoke({})
    if action == "run_python":
        return tools_mod.run_uploaded_python.invoke({
            "hostname": parsed.get("hostname"),
            "arch": parsed.get("arch"),
        })
    return "未识别的指令"
