import { Badge } from "./ui/badge";
import type { Agent } from "../lib/types";

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
          className={`min-w-0 overflow-hidden p-4 rounded-lg border-2 transition-all ${
            currentAgent === agent.name
              ? "border-blue-500 bg-blue-50"
              : "border-gray-200 bg-white hover:border-gray-300"
          }`}
        >
          <div className="flex min-w-0 items-start justify-between gap-2">
            <div className="min-w-0 flex-1">
              <h3 className="font-semibold text-sm text-gray-900">
                {agent.name}
              </h3>
              <p className="text-xs text-gray-600 mt-1 break-words [overflow-wrap:anywhere]">
                {agent.description}
              </p>
            </div>
            {currentAgent === agent.name && (
              <Badge variant="default" className="ml-2">
                Active
              </Badge>
            )}
          </div>
          
          {agent.tools.length > 0 && (
            <div className="mt-3">
              <h4 className="text-xs font-medium text-gray-700 mb-1">
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
              <h4 className="text-xs font-medium text-gray-700 mb-1">
                可转交给:
              </h4>
              <div className="flex flex-wrap gap-1">
                {[...new Set(agent.handoffs)].map((handoff, handoffIndex) => (
                  <Badge key={`handoff-${agentIndex}-${handoffIndex}-${handoff}`} variant="secondary" className="text-xs">
                    {handoff}
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
