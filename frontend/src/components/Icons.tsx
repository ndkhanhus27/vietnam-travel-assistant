import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement> & { size?: number };
const svgBase = (size: number) => ({ width: size, height: size, viewBox: "0 0 24 24", fill: "none", xmlns: "http://www.w3.org/2000/svg" });

export function PlusIcon({ size = 18, ...props }: IconProps) {
  return <svg {...svgBase(size)} {...props}><path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" /></svg>;
}
export function ChatIcon({ size = 16, ...props }: IconProps) {
  return <svg {...svgBase(size)} {...props}><path d="M5 6.5h14v9H10l-4 3v-3H5z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" /></svg>;
}
export function MoreIcon({ size = 18, ...props }: IconProps) {
  return <svg {...svgBase(size)} {...props}><circle cx="5" cy="12" r="1.35" fill="currentColor"/><circle cx="12" cy="12" r="1.35" fill="currentColor"/><circle cx="19" cy="12" r="1.35" fill="currentColor"/></svg>;
}
export function MenuIcon({ size = 20, ...props }: IconProps) {
  return <svg {...svgBase(size)} {...props}><path d="M4 7h16M4 12h16M4 17h16" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" /></svg>;
}
export function CloseIcon({ size = 18, ...props }: IconProps) {
  return <svg {...svgBase(size)} {...props}><path d="m6 6 12 12M18 6 6 18" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" /></svg>;
}
export function SendIcon({ size = 18, ...props }: IconProps) {
  return <svg {...svgBase(size)} {...props}><path d="M12 19V5M6.5 10.5 12 5l5.5 5.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}
export function ArchiveIcon({ size = 17, ...props }: IconProps) {
  return <svg {...svgBase(size)} {...props}><path d="M5 8h14v11H5zM4 5h16v3H4zM9 12h6" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" /></svg>;
}
export function TrashIcon({ size = 17, ...props }: IconProps) {
  return <svg {...svgBase(size)} {...props}><path d="M7 7h10l-.7 13H7.7L7 7Zm3-3h4M5 7h14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}
export function EditIcon({ size = 17, ...props }: IconProps) {
  return <svg {...svgBase(size)} {...props}><path d="m5 17 1-4 9-9 4 4-9 9-4 1z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" /></svg>;
}
export function UserIcon({ size = 17, ...props }: IconProps) {
  return <svg {...svgBase(size)} {...props}><circle cx="12" cy="8" r="3.5" stroke="currentColor" strokeWidth="1.5"/><path d="M5 20c.7-4.2 3.2-6.3 7-6.3s6.3 2.1 7 6.3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>;
}
export function LogoutIcon({ size = 17, ...props }: IconProps) {
  return <svg {...svgBase(size)} {...props}><path d="M10 5H5v14h5M14 8l4 4-4 4M9 12h9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}
export function ExternalIcon({ size = 14, ...props }: IconProps) {
  return <svg {...svgBase(size)} {...props}><path d="M13 5h6v6M19 5l-8 8M18 13v6H5V6h6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}
export function WarningIcon({ size = 18, ...props }: IconProps) {
  return <svg {...svgBase(size)} {...props}><path d="M12 4 21 20H3L12 4Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round"/><path d="M12 9v5M12 17.2v.1" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"/></svg>;
}
