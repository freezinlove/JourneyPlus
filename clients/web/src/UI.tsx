import * as Dialog from "@radix-ui/react-dialog";
import type { ReactNode } from "react";
import s from "./App.module.css";
export function Modal({
  title,
  children,
  onClose,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
}) {
  return (
    <Dialog.Root open onOpenChange={(v) => !v && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className={s.overlay} />
        <Dialog.Content className={s.modal} aria-describedby={undefined}>
          <header>
            <Dialog.Title>{title}</Dialog.Title>
            <Dialog.Close className={s.close} aria-label="关闭">
              ×
            </Dialog.Close>
          </header>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
export function Notice({
  error,
  retry,
}: {
  error: unknown;
  retry?: () => void;
}) {
  return (
    <div className={s.notice} role="alert">
      {error instanceof Error ? error.message : String(error)}{" "}
      {retry && <button onClick={retry}>重试</button>}
    </div>
  );
}
