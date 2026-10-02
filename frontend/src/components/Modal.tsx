import type { ReactNode } from "react";
import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { CloseIcon } from "./Icons";

type Props = {
  title: string;
  children: ReactNode;
  onClose: () => void;
  labelledBy?: string;
  className?: string;
};

export function Modal({
  title,
  children,
  onClose,
  labelledBy = "dialog-title",
  className = "",
}: Props) {
  const dialogRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const focusable = () => Array.from(
      dialogRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), a[href], input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ) || [],
    );
    const listener = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key !== "Tab") return;
      const items = focusable();
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", listener);
    document.body.classList.add("modal-open");
    requestAnimationFrame(() => focusable()[0]?.focus());
    return () => {
      window.removeEventListener("keydown", listener);
      document.body.classList.remove("modal-open");
      previouslyFocused?.focus();
    };
  }, [onClose]);

  return createPortal(
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section ref={dialogRef} className={`modal ${className}`.trim()} role="dialog" aria-modal="true" aria-labelledby={labelledBy}>
        <header className="modal-header">
          <h2 id={labelledBy}>{title}</h2>
          <button className="icon-button" onClick={onClose} aria-label="Đóng"><CloseIcon /></button>
        </header>
        {children}
      </section>
    </div>,
    document.body,
  );
}
