import { ChevronDown, ChevronUp } from "lucide-react";
import { useState } from "react";

interface PanelSectionProps {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
  collapsible?: boolean;
}

export function PanelSection({
  title, children, defaultOpen = true, collapsible = true,
}: PanelSectionProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <div className="surface-card min-w-0 overflow-hidden">
      <div className="flex items-center justify-between border-b border-border px-5 py-4">
        <h3 className="text-sm font-semibold">{title}</h3>
        {collapsible && (
          <button onClick={() => setIsOpen(!isOpen)} aria-label={`${isOpen ? '收起' : '展开'}${title}`} aria-expanded={isOpen} className="rounded p-1 hover:bg-muted">
            {isOpen ? <ChevronUp className="h-4 w-4 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
          </button>
        )}
      </div>
      {isOpen && <div className="p-5">{children}</div>}
    </div>
  );
}
