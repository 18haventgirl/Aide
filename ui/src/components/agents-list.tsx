import { Badge } from "./ui/badge";
import type { Agent } from "../lib/types";
import { agentDescription, agentLabel } from "../lib/agent-labels";

interface AgentsListProps {
  agents: Agent[];
  currentAgent: string;
}

export function AgentsList({ agents, currentAgent }: AgentsListProps) {
  return (
    <div className="min-w-0 space-y-3">
      {agents.map((agent, agentIndex) => (
        <div
          key={`agent-${agentIndex}-${agent.name}`}
          className={`min-w-0 overflow-hidden p-4 rounded-lg border transition-colors ${
            currentAgent === agent.name
              ? "border-primary/40 bg-primary/5"
              : "border-gray-200 bg-white hover:border-gray-300"
          }`}
        >
          <div className="flex min-w-0 items-start justify-between gap-2">
            <div className="min-w-0 flex-1">
              <h3 className="text-base font-semibold text-foreground">
                {agentLabel(agent.name)}
              </h3>
              <p className="mt-1 break-words text-sm text-muted-foreground [overflow-wrap:anywhere]">
                {agentDescription(agent.name, agent.description)}
              </p>
            </div>
            {currentAgent === agent.name && (
              <Badge variant="default" className="ml-2">
                运行中
              </Badge>
            )}
          </div>
          
          {agent.tools.length > 0 && (
            <div className="mt-3">
              <h4 className="mb-1 text-sm font-medium text-foreground">
                可用工具:
              </h4>
              <div className="flex flex-wrap gap-1">
                {agent.tools.map((tool, toolIndex) => (
                  <Badge key={`tool-${agentIndex}-${toolIndex}-${tool}`} variant="outline" className="text-xs">
                    {tool}
                  </Badge>
                ))}
              </div>
            </div>
          )}
          
          {agent.handoffs.length > 0 && (
            <div className="mt-2">
              <h4 className="mb-1 text-sm font-medium text-foreground">
                可转交给:
              </h4>
              <div className="flex flex-wrap gap-1">
                {[...new Set(agent.handoffs)].map((handoff, handoffIndex) => (
                  <Badge key={`handoff-${agentIndex}-${handoffIndex}-${handoff}`} variant="secondary" className="text-xs">
                    {agentLabel(handoff)}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
