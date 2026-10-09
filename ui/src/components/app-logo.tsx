import { Activity } from 'lucide-react';

export function AppLogo({ compact = false }: { compact?: boolean }) {
  return <div className="flex items-center gap-3">
    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary text-white">
      <Activity className="h-5 w-5" strokeWidth={2.5} />
    </span>
    {!compact && <span className="text-xl font-semibold tracking-tight">Aide<span className="text-primary">.</span></span>}
  </div>;
}
