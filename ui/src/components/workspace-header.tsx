import type { ReactNode } from 'react';

/** Shared heading and action layout for every workspace. */
export function WorkspaceHeader({ title, description, actions }: {
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return <header className="workspace-header">
    <div className="min-w-0">
      <h1 className="text-xl font-semibold tracking-tight text-foreground sm:text-2xl">{title}</h1>
      <p className="mt-1.5 hidden text-sm leading-6 text-muted-foreground sm:block">{description}</p>
    </div>
    {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
  </header>;
}
