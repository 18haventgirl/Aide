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
    <div className="border-b border-border/40 pb-3 last:border-b-0">
      <div
        className={`flex items-center justify-between mb-2.5 px-1 ${collapsible ? "cursor-pointer" : ""}`}
        onClick={() => collapsible && setIsOpen(!isOpen)}
      >
        <h3 className="text-sm font-heading font-semibold text-foreground/80">{title}</h3>
        {collapsible && (
          <button className="p-1 rounded hover:bg-muted transition-colors">
            {isOpen ? <ChevronUp className="h-4 w-4 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
          </button>
        )}
      </div>
      {isOpen && <div>{children}</div>}
    </div>
  );
}