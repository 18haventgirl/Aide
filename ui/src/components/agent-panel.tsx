import { Bot } from "lucide-react";
import { WorkspaceHeader } from './workspace-header';
import type { Agent, AgentEvent, GuardrailCheck } from "../lib/types";
import { AgentsList } from "./agents-list";
import { ConversationContext } from "./conversation-context";
import { RunnerOutput } from "./runner-output";
import { PanelSection } from "./panel-section";

interface AgentPanelProps {
  agents: Agent[];
  currentAgent: string;
  events: AgentEvent[];
  guardrails: GuardrailCheck[];
  context: Record<string, unknown>;
}

export function AgentPanel({
  agents,
  currentAgent,
  events,
  context,
}: AgentPanelProps) {
  const runnerEvents = events.filter((e) => e.type !== "message");

  return (
    <div className="w-full h-full min-h-0 min-w-0 flex flex-col">
      <WorkspaceHeader title="智能体" description="了解助手如何协作，查看当前任务与运行过程。" />

      <div className="flex-1 min-h-0 min-w-0 overflow-y-auto px-5 pb-5 sm:px-8 sm:pb-8">
        <div className="mx-auto grid max-w-6xl items-start gap-5 xl:grid-cols-2">
        <PanelSection title="智能体状态" defaultOpen={true}>
          {agents.length > 0 ? <AgentsList agents={agents} currentAgent={currentAgent} /> : <div className="flex flex-col items-center px-4 py-10 text-center"><span className="mb-4 rounded-xl bg-muted p-3"><Bot className="h-6 w-6 text-muted-foreground" /></span><p className="text-sm font-medium">等待任务开始</p><p className="mt-2 max-w-xs text-xs leading-6 text-muted-foreground">连接聊天服务并发起对话后，参与任务的智能体会显示在这里。</p></div>}
        </PanelSection>

        {/* 安全护栏功能已暂时隐藏 */}
        {/*
        <PanelSection title="安全护栏" defaultOpen={true}>
          <Guardrails
            guardrails={guardrails}
            inputGuardrails={activeAgent?.input_guardrails ?? []}
          />
        </PanelSection>
        */}

        <div className="min-w-0 space-y-5">
        <PanelSection title="对话上下文" defaultOpen={true}>
          <ConversationContext context={context} />
        </PanelSection>

        <PanelSection title="运行输出" defaultOpen={true}>
          <RunnerOutput runnerEvents={runnerEvents} />
        </PanelSection>
        </div>
        </div>
      </div>
    </div>
  );
}
