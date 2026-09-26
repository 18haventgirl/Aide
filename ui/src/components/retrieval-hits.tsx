import { FileSearch } from "lucide-react";
import type { RetrievalHit } from "../lib/types";

/** 本轮前置检索命中：回答里用到的笔记片段，来自 retrieval 过程帧 */
export function RetrievalHits({ hits }: { hits: RetrievalHit[] }) {
  if (!hits.length) return <div className="text-xs text-gray-500 italic">本轮无检索命中</div>;

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-[11px] text-gray-500">
        <FileSearch className="h-3.5 w-3.5" />
        <span>{hits.length} 条命中</span>
      </div>
      <ul className="space-y-1">
        {hits.map((hit) => (
          <li key={hit.id ?? hit.title} className="rounded-md border border-gray-200 bg-white px-2.5 py-1.5">
            <div className="flex items-center gap-2">
              <span className="truncate text-xs font-medium text-gray-900">{hit.title}</span>
              <span className="ml-auto flex-shrink-0 text-[11px] text-gray-600">
                {hit.score.toFixed(2)}
              </span>
            </div>
            <p className="mt-0.5 line-clamp-2 text-[11px] text-gray-600">{hit.text}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
