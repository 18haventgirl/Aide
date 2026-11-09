import type { ReactNode } from 'react';

/** Shared heading and action layout for every workspace. */
export function WorkspaceHeader({ title, description, actions }: {
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return <header className="workspace-header">
    <div className="min-w-0">
      <h1 className="text-2xl font-semibold tracking-tight text-foreground sm:text-[1.75rem]">{title}</h1>
      <p className="mt-1 text-sm leading-6 text-muted-foreground sm:mt-1.5">{description}</p>
    </div>
    {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
  </header>;
}
