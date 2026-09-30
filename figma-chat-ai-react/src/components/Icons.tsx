import type { SVGProps } from "react";

type Props = SVGProps<SVGSVGElement> & { size?: number };

const base = (size: number) => ({ width: size, height: size, viewBox: "0 0 24 24", fill: "none", xmlns: "http://www.w3.org/2000/svg" });

export function PlusIcon({ size = 18, ...props }: Props) {
  return <svg {...base(size)} {...props}><path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"/></svg>;
}
export function SearchIcon({ size = 18, ...props }: Props) {
  return <svg {...base(size)} {...props}><circle cx="11" cy="11" r="6" stroke="currentColor" strokeWidth="1.7"/><path d="m16 16 3.5 3.5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"/></svg>;
}
export function ChatIcon({ size = 16, ...props }: Props) {
  return <svg {...base(size)} {...props}><path d="M5 6.5h14v9H10l-4 3v-3H5z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round"/></svg>;
}
export function TrashIcon({ size = 16, ...props }: Props) {
  return <svg {...base(size)} {...props}><path d="M8 8v10M12 8v10M16 8v10M5 6h14M9 4h6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>;
}
export function EditIcon({ size = 16, ...props }: Props) {
  return <svg {...base(size)} {...props}><path d="m6 17 1.2-4.5L15.7 4 20 8.3l-8.5 8.5L7 18z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round"/></svg>;
}
export function GearIcon({ size = 16, ...props }: Props) {
  return <svg {...base(size)} {...props}><circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.5"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6 7 7M17 17l1.4 1.4M18.4 5.6 17 7M7 17l-1.4 1.4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>;
}
export function SendIcon({ size = 18, ...props }: Props) {
  return <svg {...base(size)} {...props}><path d="m4 12 15-7-5 15-2.6-5.4z" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round"/></svg>;
}
export function LikeIcon({ size = 16, ...props }: Props) {
  return <svg {...base(size)} {...props}><path d="M8 11v8H4v-8h4Zm0 6h8.5a2 2 0 0 0 2-1.7l.7-5A2 2 0 0 0 17.2 8H14l.5-2.2A2.2 2.2 0 0 0 12.4 3L8 11Z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/></svg>;
}
export function DislikeIcon({ size = 16, ...props }: Props) {
  return <svg {...base(size)} {...props} style={{ transform: "rotate(180deg)" }}><path d="M8 11v8H4v-8h4Zm0 6h8.5a2 2 0 0 0 2-1.7l.7-5A2 2 0 0 0 17.2 8H14l.5-2.2A2.2 2.2 0 0 0 12.4 3L8 11Z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/></svg>;
}
export function CopyIcon({ size = 16, ...props }: Props) {
  return <svg {...base(size)} {...props}><rect x="8" y="8" width="10" height="10" rx="1" stroke="currentColor" strokeWidth="1.5"/><path d="M6 15H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h7a2 2 0 0 1 2 2v1" stroke="currentColor" strokeWidth="1.5"/></svg>;
}
export function MoreIcon({ size = 16, ...props }: Props) {
  return <svg {...base(size)} {...props}><circle cx="12" cy="5" r="1.2" fill="currentColor"/><circle cx="12" cy="12" r="1.2" fill="currentColor"/><circle cx="12" cy="19" r="1.2" fill="currentColor"/></svg>;
}
export function RefreshIcon({ size = 15, ...props }: Props) {
  return <svg {...base(size)} {...props}><path d="M19 8a8 8 0 1 0 1 7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/><path d="M19 4v4h-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>;
}
