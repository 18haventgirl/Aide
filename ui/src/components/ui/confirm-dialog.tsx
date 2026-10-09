import { useEffect, useId, useRef } from 'react';
import { Button } from './button';

export interface Confirmation {
  title: string;
  description: string;
  confirmLabel: string;
  destructive?: boolean;
  onConfirm: () => void;
}

/** Native dialog supplies focus containment and Escape handling without blocking the browser. */
export function ConfirmDialog({ confirmation, onDismiss }: { confirmation: Confirmation; onDismiss: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);

  return <dialog ref={dialog} role="alertdialog" aria-labelledby={titleId} aria-describedby={descriptionId}
    onCancel={onDismiss} className="m-auto w-[calc(100%_-_2rem)] max-w-sm rounded-xl border border-border bg-card p-6 text-foreground shadow-xl backdrop:bg-slate-950/40">
    <h2 id={titleId} className="text-base font-semibold">{confirmation.title}</h2>
    <p id={descriptionId} className="mt-3 text-sm leading-7 text-muted-foreground">{confirmation.description}</p>
    <div className="mt-6 flex justify-end gap-2">
      <Button variant="outline" onClick={onDismiss} autoFocus>取消</Button>
      <Button variant={confirmation.destructive ? 'destructive' : 'default'} onClick={() => { onDismiss(); confirmation.onConfirm(); }}>{confirmation.confirmLabel}</Button>
    </div>
  </dialog>;
}
