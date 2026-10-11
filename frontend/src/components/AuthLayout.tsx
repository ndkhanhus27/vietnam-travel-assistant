import type { ReactNode } from "react";
import { GlobalOutlined, MoonOutlined, SunOutlined } from "@ant-design/icons";
import { Button } from "antd";
import { useAppearance } from "../appearance/AppearanceProvider";
import { useLocale } from "../locale/LocaleProvider";

export function AuthLayout({ children }: { children: ReactNode }) {
  const { t } = useLocale();
  const { resolvedMode, setMode } = useAppearance();
  return <main className="auth-page">
    <div className="auth-utilities">
      <Button
        type="text"
        shape="circle"
        aria-label={t("Đổi chế độ sáng tối", "Toggle light and dark mode")}
        icon={resolvedMode === "dark" ? <SunOutlined /> : <MoonOutlined />}
        onClick={() => setMode(resolvedMode === "dark" ? "light" : "dark")}
      />
    </div>
    <section className="auth-story" aria-label={t("Trợ lý du lịch Việt Nam", "Vietnam travel assistant")}>
      <div className="auth-story-brand">VIETNAM TRAVEL ADVISOR</div>
      <div className="auth-story-copy">
        <span className="auth-story-kicker"><GlobalOutlined /> {t("Du lịch Việt Nam", "Explore Vietnam")}</span>
        <h2>{t("Khám phá Việt Nam theo cách phù hợp với bạn.", "Explore Vietnam your way.")}</h2>
        <p>{t("Hỏi, so sánh, lên lịch trình và nhận gợi ý du lịch có căn cứ.", "Ask, compare, plan itineraries, and get grounded travel advice.")}</p>
        <div className="auth-story-points">
          <span>{t("Khám phá điểm đến", "Discover destinations")}</span>
          <span>{t("So sánh lựa chọn", "Compare options")}</span>
          <span>{t("Lên lịch trình", "Build itineraries")}</span>
        </div>
      </div>
    </section>
    <section className="auth-panel" aria-labelledby="auth-title">{children}</section>
  </main>;
}
