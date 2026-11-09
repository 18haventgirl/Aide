import { Activity } from 'lucide-react';

export function AppLogo({ compact = false }: { compact?: boolean }) {
  return <div className="flex items-center gap-3">
    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary text-white shadow-sm">
      <Activity className="h-5 w-5" strokeWidth={2.5} />
    </span>
    {!compact && <span className="text-[1.375rem] font-semibold tracking-tight">Aide<span className="text-primary">.</span></span>}
  </div>;
}
