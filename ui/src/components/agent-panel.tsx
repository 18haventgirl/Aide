import { Bot } from "lucide-react";
import type { Agent, AgentEvent, GuardrailCheck, NodeUpdate, RetrievalHit, ToolInfo } from "../lib/types";
import { GraphTrace } from "./graph-trace";
import { RetrievalHits } from "./retrieval-hits";
import { ToolList } from "./tool-list";
import { Guardrails } from "./guardrails";
import { ConversationContext } from "./conversation-context";
import { RunnerOutput } from "./runner-output";
import { PanelSection } from "./panel-section";

interface AgentPanelProps {
  agents: Agent[];
  currentAgent: string;
  events: AgentEvent[];
  guardrails: GuardrailCheck[];
  // 上下文键由后端 UserContext 决定，前端只做通用展示
  context: Record<string, unknown>;
  graphNodes: NodeUpdate[];
  toolInfos: ToolInfo[];
  retrievalHits: RetrievalHit[];
}

export function AgentPanel({
  agents,
  currentAgent,
  events,
  guardrails,
  context,
  graphNodes,
  toolInfos,
  retrievalHits,
}: AgentPanelProps) {
  const activeAgent = agents.find((a) => a.name === currentAgent);
  // 检索命中有独立分区，不再在运行输出里重复一行
  const runnerEvents = events.filter((e) => e.type !== "message" && e.type !== "retrieval");

  return (
    <div className="w-full h-full flex flex-col bg-transparent">
      <div className="bg-gradient-to-r from-primary to-blue-600 text-white h-12 px-4 flex items-center gap-3 shadow-sm md:rounded-t-xl flex-shrink-0">
        <Bot className="h-5 w-5" />
        <h1 className="font-semibold text-sm sm:text-base lg:text-lg">Agent View</h1>
        <span className="ml-auto text-xs font-light tracking-wide opacity-80">
          LangGraph 单代理
        </span>
      </div>

      <div className="flex-1 overflow-y-auto p-4 md:p-6 bg-gray-50 space-y-4 md:space-y-6">
        <PanelSection title="执行节点" defaultOpen={true}>
          <GraphTrace nodes={graphNodes} />
        </PanelSection>

        <PanelSection title="笔记检索命中" defaultOpen={true}>
          <RetrievalHits hits={retrievalHits} />
        </PanelSection>

        <PanelSection title="工具" defaultOpen={false}>
          <ToolList tools={toolInfos} />
        </PanelSection>

        <PanelSection title="护栏" defaultOpen={true}>
          <Guardrails
            guardrails={guardrails}
            inputGuardrails={activeAgent?.input_guardrails ?? []}
          />
        </PanelSection>

        <PanelSection title="上下文" defaultOpen={true}>
          <ConversationContext context={context} />
        </PanelSection>

        <PanelSection title="运行输出" defaultOpen={true}>
          <RunnerOutput runnerEvents={runnerEvents} />
        </PanelSection>
      </div>
    </div>
  );
} 