"""轻量 Agent 工作流引擎（StateGraph）。

接口与 LangGraph 对齐（add_node / add_edge / add_conditional_edges / compile / invoke），
但只用标准库实现，不引入额外依赖，便于独立迁移：
- 若要换成官方 LangGraph，只需把 backend/agent/workflows.py 中的 StateGraph
  替换为 langgraph.graph.StateGraph，节点函数签名保持一致即可。

节点签名：  fn(state: dict, ctx: RunContext) -> dict        # 返回对 state 的增量更新
路由签名：  router(state: dict) -> str                       # 返回映射表中的 key
"""
from __future__ import annotations

import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

NodeFn = Callable[[dict, "RunContext"], dict]
RouterFn = Callable[[dict], str]

#: 流程终止标记。节点执行完毕后若指向此值，则结束整个工作流。
END = "__END__"


@dataclass
class RunContext:
    """运行时依赖，不进入 state，避免被序列化。"""

    db: Any = None
    extras: dict = field(default_factory=dict)

    def get(self, key: str, default=None):
        return self.extras.get(key, default)


@dataclass
class NodeSpec:
    name: str
    fn: NodeFn
    description: str = ""


class StateGraph:
    def __init__(self, name: str = "graph") -> None:
        self.name = name
        self.nodes: dict[str, NodeSpec] = {}
        self.edges: dict[str, str] = {}
        self.conditional: dict[str, tuple[RouterFn, dict[str, str]]] = {}
        self.entry: str | None = None
        self.finish: str = END
        self.finish_node: str | None = None

    # ---------------------------------------------------------- 构建
    def add_node(self, name: str, fn: NodeFn, description: str = "") -> "StateGraph":
        if name in self.nodes:
            raise ValueError(f"节点重名：{name}")
        self.nodes[name] = NodeSpec(name=name, fn=fn, description=description)
        return self

    def add_edge(self, src: str, dst: str) -> "StateGraph":
        self.edges[src] = dst
        return self

    def add_conditional_edges(self, src: str, router: RouterFn, mapping: dict[str, str]) -> "StateGraph":
        self.conditional[src] = (router, mapping)
        return self

    def set_entry_point(self, name: str) -> "StateGraph":
        self.entry = name
        return self

    def set_finish_point(self, name: str) -> "StateGraph":
        """标记终点节点：该节点仍然会执行，执行完即结束。"""
        self.finish_node = name
        self.edges[name] = END
        return self

    # ---------------------------------------------------------- 说明
    def describe(self) -> dict:
        return {
            "name": self.name,
            "entry": self.entry,
            "finish": self.finish_node or "(未指定)",
            "nodes": [
                {
                    "name": n.name,
                    "description": n.description,
                    "next": self._next_of(n.name),
                }
                for n in self.nodes.values()
            ],
        }

    def _next_of(self, name: str) -> Any:
        if name in self.conditional:
            _, mapping = self.conditional[name]
            return {"type": "conditional", "branches": mapping}
        target = self.edges.get(name, END)
        return {"type": "edge", "target": "结束" if target == END else target}

    def to_mermaid(self) -> str:
        lines = ["flowchart TD"]
        for n in self.nodes.values():
            label = f"{n.name}<br/>{n.description}" if n.description else n.name
            lines.append(f'    {_safe(n.name)}["{label}"]')
        for src, dst in self.edges.items():
            if dst == END:
                continue
            lines.append(f"    {_safe(src)} --> {_safe(dst)}")
        for src, (_, mapping) in self.conditional.items():
            for key, dst in mapping.items():
                if dst == END:
                    continue
                lines.append(f"    {_safe(src)} -->|{key}| {_safe(dst)}")
        return "\n".join(lines)

    # ---------------------------------------------------------- 执行
    def compile(self, max_steps: int = 40) -> "CompiledGraph":
        if not self.entry:
            raise ValueError("未设置入口节点")
        for src in list(self.edges) + list(self.conditional):
            if src not in self.nodes:
                raise ValueError(f"边引用了不存在的节点：{src}")
        return CompiledGraph(self, max_steps=max_steps)


class CompiledGraph:
    def __init__(self, graph: StateGraph, max_steps: int = 40) -> None:
        self.graph = graph
        self.max_steps = max_steps

    def invoke(self, state: dict, ctx: RunContext | None = None) -> dict:
        ctx = ctx or RunContext()
        state = dict(state)
        trace: list[dict] = state.setdefault("_trace", [])
        current = self.graph.entry
        steps = 0
        started = time.time()

        while current and current != self.graph.finish and steps < self.max_steps:
            steps += 1
            spec = self.graph.nodes.get(current)
            if spec is None:
                raise KeyError(f"节点不存在：{current}")

            t0 = time.time()
            entry = {"node": current, "description": spec.description, "status": "ok"}
            try:
                update = spec.fn(state, ctx) or {}
                if not isinstance(update, dict):
                    raise TypeError(f"节点 {current} 必须返回 dict，实际为 {type(update).__name__}")
                state.update(update)
            except Exception as e:
                entry.update(
                    {
                        "status": "error",
                        "error": f"{type(e).__name__}: {e}",
                        "traceback": traceback.format_exc(limit=3),
                    }
                )
                trace.append(entry)
                state["_error"] = entry["error"]
                raise
            finally:
                if not entry.get("duration_ms"):
                    entry["duration_ms"] = int((time.time() - t0) * 1000)
            trace.append(entry)
            current = self._resolve_next(current, state)

        state["_steps"] = steps
        state["_duration_ms"] = int((time.time() - started) * 1000)
        state.pop("_error", None)
        return state

    def _resolve_next(self, current: str, state: dict) -> str:
        if current in self.graph.conditional:
            router, mapping = self.graph.conditional[current]
            key = router(state)
            target = mapping.get(key) or mapping.get("default")
            if target is None:
                raise KeyError(f"条件路由 {current} 返回了未映射的 key：{key}")
            return target
        return self.graph.edges.get(current, self.graph.finish)


def _safe(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)


def node(state: dict, key: str, default=None):
    return state.get(key, default)
