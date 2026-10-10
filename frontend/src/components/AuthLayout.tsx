import type { ReactNode } from "react";
import { Plane } from "lucide-react";

export function AuthLayout({ children }: { children: ReactNode }) {
  return <main className="auth-page">
    <section className="auth-story" aria-label="Trợ lý du lịch Việt Nam">
      <div className="auth-story-brand"><Plane size={22} aria-hidden="true" />TRAVEL A.I+</div>
      <div className="auth-story-copy"><h2>Bạn muốn đi đâu?</h2><p>Cùng lên kế hoạch cho chuyến đi tiếp theo.</p></div>
    </section>
    <section className="auth-panel" aria-labelledby="auth-title">{children}</section>
  </main>;
}
