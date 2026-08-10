import React, { useState, useEffect } from 'react';
import { FileText, CheckSquare, Layout } from 'lucide-react';
import { NotesPanel } from './notes-panel';
import { TodosPanel } from './todos-panel';
import type { PersonDataTab } from '../lib/types';
import { useAppSelector } from '../store/hooks';

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
  ];

  return (
    <div className="w-full h-full flex flex-col bg-transparent">
      <div className="h-12 flex-shrink-0 bg-gradient-to-r from-primary to-blue-600 text-white px-4 flex items-center gap-2.5">
        <Layout className="h-4 w-4" />
        <h2 className="font-heading font-semibold text-sm">个人数据</h2>
      </div>

      <div className="flex border-b border-border/30 bg-muted/20">
        {tabs.map(([tab, Icon, label]) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`flex-1 py-2.5 text-sm font-medium flex items-center justify-center gap-2 transition-colors ${
              activeTab === tab
                ? 'text-primary border-b-2 border-primary bg-white/60'
                : 'text-muted-foreground hover:text-foreground hover:bg-muted/50'
            }`}
          >
            <Icon className="w-4 h-4" />
            <span>{label}</span>
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-hidden bg-background">
        {activeTab === 'notes' && <NotesPanel userId={currentUserId} />}
        {activeTab === 'todos' && <TodosPanel userId={currentUserId} />}
      </div>
    </div>
  );
}