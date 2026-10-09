import { Database } from "lucide-react";
import React from "react";

interface ConversationContextProps {
  context: Record<string, unknown>;
}

export function ConversationContext({ context }: ConversationContextProps) {
  const contextEntries = Object.entries(context).filter(([, value]) => value !== null && value !== undefined && value !== '');

  return (
    <div className="min-w-0 max-w-full space-y-3">
      {contextEntries.length === 0 && (
        <div className="flex items-center gap-3 py-4 text-sm text-muted-foreground"><Database className="h-5 w-5" />暂无上下文信息</div>
      )}
      
      {contextEntries.length > 0 && <div className="min-w-0 max-w-full overflow-hidden rounded-lg bg-muted/50 p-3">
        <div className="grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-3 gap-y-2">
          {contextEntries.map(([key, value], index) => (
            <React.Fragment key={`context-${index}-${key}`}>
              <span className="min-w-0 text-xs font-medium text-gray-600 capitalize break-words">
                {key.replace(/_/g, ' ')}:
              </span>
              <span className="min-w-0 max-w-full text-right text-xs text-gray-900 font-mono break-words [overflow-wrap:anywhere]">
                {typeof value === 'string' ? value : JSON.stringify(value)}
              </span>
            </React.Fragment>
          ))}
        </div>
      </div>}
      
      <div className="text-xs text-gray-400">
        上下文信息会在对话过程中动态更新
      </div>
    </div>
  );
}
