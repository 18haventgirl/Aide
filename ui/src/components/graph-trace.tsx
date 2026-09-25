import { GitBranch } from "lucide-react";
import type { NodeUpdate } from "../lib/types";

/** 节点名到中文标签：后端上报的是 LangGraph 节点标识，直接摊给用户读不懂 */
const NODE_LABELS: Record<string, string> = {
  "Safety Guardrail.before_model": "安全护栏",
  "Relevance Guardrail.before_model": "相关性护栏",
  model: "模型推理",
  tools: "工具执行",
};

export function nodeLabel(node: string): string {
  return NODE_LABELS[node] ?? node;
}

interface GraphTraceProps {
  nodes: NodeUpdate[];
}

/**
 * 图执行轨迹：按节点首次出现的顺序列出，状态取最后一次上报
 * （同一节点会被多次刷新，只保留最新状态，不然一轮工具回环就刷屏）
 */
export function GraphTrace({ nodes }: GraphTraceProps) {
  const order: string[] = [];
  const status: Record<string, "started" | "finished"> = {};

  for (const update of nodes) {
    if (!update?.node) continue;
    if (!order.includes(update.node)) order.push(update.node);
    status[update.node] = update.status === "finished" ? "finished" : "started";
  }

  // 分区标题由外层 PanelSection 负责，这里不再重复一遍
  return (
    <div className="space-y-2">
      {order.length > 0 && (
        <div className="flex items-center gap-2 text-[11px] text-gray-500">
          <GitBranch className="h-3.5 w-3.5" />
          <span>{order.length} 个节点</span>
          <span>·</span>
          <span>{order.filter((n) => status[n] === "finished").length} 已完成</span>
        </div>
      )}

      {order.length === 0 ? (
        <div className="text-xs text-gray-500 italic">本轮尚未开始执行</div>
      ) : (
        <ol className="space-y-1.5">
          {order.map((node) => {
            const running = status[node] !== "finished";
            return (
              <li
                key={node}
                className={`flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-xs transition-colors ${
                  running ? "border-blue-200 bg-blue-50" : "border-gray-200 bg-white"
                }`}
              >
                <span
                  className={`h-2 w-2 flex-shrink-0 rounded-full ${
                    running ? "animate-pulse bg-blue-500" : "bg-green-500"
                  }`}
                />
                <span className="font-medium text-gray-900">{nodeLabel(node)}</span>
                <span className="truncate font-mono text-[10px] text-gray-500">{node}</span>
                <span className="ml-auto flex-shrink-0 text-gray-600">
                  {running ? "执行中" : "已完成"}
                </span>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
