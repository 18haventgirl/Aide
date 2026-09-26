import { Wrench } from "lucide-react";
import type { ToolInfo } from "../lib/types";

interface ToolGroup {
  key: string;
  label: string;
  test: (name: string) => boolean;
}

/** 按来源分组：笔记工具与 MCP 外部工具分开 */
const GROUPS: ToolGroup[] = [
  { key: "note", label: "笔记检索", test: (n) => n === "search_my_notes" || n === "save_note" },
  { key: "weather", label: "天气", test: (n) => n.startsWith("weather_") },
  { key: "recipe", label: "菜谱", test: (n) => n.startsWith("recipe_") },
  { key: "news", label: "新闻", test: (n) => n.startsWith("news_") },
  { key: "user", label: "用户数据", test: (n) => n.startsWith("user_data_") },
];

function groupOf(name: string): string {
  return GROUPS.find((group) => group.test(name))?.key ?? "other";
}

interface ToolListProps {
  tools: ToolInfo[];
}

export function ToolList({ tools }: ToolListProps) {
  const valid = (tools || []).filter((tool) => tool?.name);

  // 分区标题由外层 PanelSection 负责，这里不再重复一遍
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-[11px] text-gray-500">
        <Wrench className="h-3.5 w-3.5" />
        <span>{valid.length} 个工具</span>
      </div>

      {valid.length === 0 ? (
        <div className="text-xs text-gray-500 italic">
          还没有收到工具清单（MCP 未连接时本轮只有本地工具或纯对话）
        </div>
      ) : (
        <div className="space-y-3">
          {[...GROUPS.map((group) => group.key), "other"]
            .filter((key, index, all) => all.indexOf(key) === index)
            .map((key) => {
              const items = valid.filter((tool) => groupOf(tool.name) === key);
              if (items.length === 0) return null;
              const label = GROUPS.find((group) => group.key === key)?.label ?? "其他";
              return (
                <div key={key} className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-gray-700">{label}</span>
                    <span className="rounded-full bg-gray-100 px-1.5 text-[10px] text-gray-600">
                      {items.length}
                    </span>
                  </div>
                  <ul className="space-y-1">
                    {items.map((tool) => (
                      <li key={tool.name} className="rounded-md border border-gray-200 bg-white px-2.5 py-1.5">
                        <span className="font-mono text-[11px] text-gray-900">{tool.name}</span>
                        {tool.description && (
                          <p className="mt-0.5 line-clamp-2 text-[11px] leading-snug text-gray-600">
                            {tool.description}
                          </p>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })}
        </div>
      )}
    </div>
  );
}
