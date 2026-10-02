import type { ReactNode } from "react";
import { useEffect } from "react";
import { CloseIcon } from "./Icons";

type Props = {
  title: string;
  children: ReactNode;
  onClose: () => void;
  labelledBy?: string;
};

export function Modal({ title, children, onClose, labelledBy = "dialog-title" }: Props) {
  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, [onClose]);

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <section className="modal" role="dialog" aria-modal="true" aria-labelledby={labelledBy}>
        <header className="modal-header">
          <h2 id={labelledBy}>{title}</h2>
          <button className="icon-button" onClick={onClose} aria-label="Đóng"><CloseIcon /></button>
        </header>
        {children}
      </section>
    </div>
  );
}
