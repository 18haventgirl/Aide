import React, { useState, useEffect } from 'react';
import { FileText, CheckSquare, Activity } from 'lucide-react';
import { WorkspaceHeader } from './workspace-header';
import { NotesPanel } from './notes-panel';
import { TodosPanel } from './todos-panel';
import type { PersonDataTab } from '../lib/types';
import { useAppSelector } from '../store/hooks';
import { HealthRecordsPanel } from './health-records-panel';

interface PersonDataPanelProps { userId?: number }

export function PersonDataPanel({ userId }: PersonDataPanelProps) {
  const [activeTab, setActiveTab] = useState<PersonDataTab>('notes');
  const [currentUserId, setCurrentUserId] = useState<number>(userId || 1);
  const { user } = useAppSelector(s => s.auth);

  useEffect(() => {
    if (user?.user_id) setCurrentUserId(parseInt(user.user_id));
    else if (userId) setCurrentUserId(userId);
  }, [user, userId]);

  const tabs: [PersonDataTab, React.ElementType, string][] = [
    ['notes', FileText, '笔记'],
    ['todos', CheckSquare, '待办'],
    ['health', Activity, '身体状况'],
  ];

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      <WorkspaceHeader title="个人数据" description="把日常笔记、待办与健康记录，妥善整理在一起。" />
      <div className="mx-5 mb-5 flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-border bg-card sm:mx-8 sm:mb-8">
      <div className="flex shrink-0 gap-1 border-b border-border px-3 sm:px-5" role="tablist" aria-label="个人数据分类">
        {tabs.map(([tab, Icon, label]) => (
          <button
            key={tab}
            role="tab"
            aria-selected={activeTab === tab}
            onClick={() => setActiveTab(tab)}
            className={`flex-1 whitespace-nowrap rounded-none py-4 text-xs font-medium flex items-center justify-center gap-1 transition-colors sm:flex-none sm:gap-2 sm:px-5 sm:text-sm ${
              activeTab === tab
                ? 'text-primary border-b-2 border-primary'
                : 'text-muted-foreground hover:text-foreground hover:bg-muted/50'
            }`}
          >
            <Icon className="w-4 h-4" />
            <span>{label}</span>
          </button>
        ))}
      </div>

      <div className="min-h-0 flex-1 overflow-hidden">
        {activeTab === 'notes' && <NotesPanel userId={currentUserId} />}
        {activeTab === 'todos' && <TodosPanel userId={currentUserId} />}
        {activeTab === 'health' && <HealthRecordsPanel userId={currentUserId} />}
      </div>
      </div>
    </div>
  );
}
