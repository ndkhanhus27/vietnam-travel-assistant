import { useEffect, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type {
  AdminAgentRunPage,
  AdminOverview,
  AdminUser,
  AdminUserPage,
} from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { BackIcon, UsersIcon } from "../components/Icons";

type AdminView = "overview" | "users" | "runs";

export function AdminPage() {
  const { user } = useAuth();
  const [view, setView] = useState<AdminView>("overview");
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [users, setUsers] = useState<AdminUserPage | null>(null);
  const [runs, setRuns] = useState<AdminAgentRunPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!user?.is_admin) return;
    let active = true;
    setLoading(true);
    setError("");
    const request = view === "overview"
      ? api.adminOverview().then((value) => active && setOverview(value))
      : view === "users"
        ? api.adminUsers().then((value) => active && setUsers(value))
        : api.adminAgentRuns().then((value) => active && setRuns(value));
    request.catch((cause) => {
      if (!active) return;
      setError(cause instanceof ApiError ? cause.message : "Không thể tải dữ liệu quản trị.");
    }).finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [user?.is_admin, view]);

  if (!user?.is_admin) return <Navigate to="/" replace />;

  async function toggleUser(target: AdminUser) {
    setError("");
    try {
      const updated = await api.updateAdminUser(target.id, !target.is_active);
      setUsers((current) => current ? {
        ...current,
        items: current.items.map((item) => item.id === updated.id ? updated : item),
      } : current);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Không thể cập nhật tài khoản.");
    }
  }

  return (
    <main className="admin-page">
      <aside className="admin-sidebar">
        <Link to="/" className="admin-back"><BackIcon />Quay lại trò chuyện</Link>
        <div className="admin-brand"><UsersIcon /><span>Quản trị hệ thống</span></div>
        <nav aria-label="Các mục quản trị">
          <button className={view === "overview" ? "is-active" : ""} onClick={() => setView("overview")}>Tổng quan</button>
          <button className={view === "users" ? "is-active" : ""} onClick={() => setView("users")}>Người dùng</button>
          <button className={view === "runs" ? "is-active" : ""} onClick={() => setView("runs")}>Hoạt động trợ lý</button>
        </nav>
      </aside>
      <section className="admin-content">
        <header className="admin-header">
          <div><p>Vận hành nội bộ</p><h1>{view === "runs" ? "Hoạt động của trợ lý" : view === "users" ? "Người dùng" : "Tổng quan"}</h1></div>
          <span>{user.email}</span>
        </header>
        {error && <div className="inline-error" role="alert">{error}</div>}
        {loading ? <div className="admin-loading">Đang tải...</div> : null}
        {!loading && view === "overview" && overview ? <Overview data={overview} /> : null}
        {!loading && view === "users" && users ? <UsersTable page={users} currentUserId={user.id} onToggle={toggleUser} /> : null}
        {!loading && view === "runs" && runs ? <RunsTable page={runs} /> : null}
      </section>
    </main>
  );
}

function Overview({ data }: { data: AdminOverview }) {
  const metrics = [
    ["Tổng người dùng", data.total_users],
    ["Đang hoạt động", data.active_users],
    ["Cuộc trò chuyện", data.total_conversations],
    ["Yêu cầu hôm nay", data.requests_today],
    ["Thành công", data.successful_runs],
    ["Hoàn thành một phần", data.degraded_runs],
    ["Thất bại", data.failed_runs],
    ["Độ trễ trung bình", data.average_latency_ms === null ? "-" : `${Math.round(data.average_latency_ms)} ms`],
    ["Độ trễ p50", data.p50_latency_ms === null ? "-" : `${Math.round(data.p50_latency_ms)} ms`],
    ["Độ trễ p95", data.p95_latency_ms === null ? "-" : `${Math.round(data.p95_latency_ms)} ms`],
  ];
  return <><div className="metric-grid">{metrics.map(([label, value]) => <div className="metric-item" key={label}><span>{label}</span><strong>{value}</strong></div>)}</div><section className="admin-section"><h2>Mức sử dụng công cụ</h2><div className="tool-usage">{Object.entries(data.tool_usage).length ? Object.entries(data.tool_usage).map(([tool, count]) => <div key={tool}><span>{toolLabel(tool)}</span><strong>{count}</strong></div>) : <p>Chưa ghi nhận lượt sử dụng công cụ nào.</p>}</div></section></>;
}

function UsersTable({ page, currentUserId, onToggle }: { page: AdminUserPage; currentUserId: string; onToggle: (user: AdminUser) => void }) {
  return <section className="admin-section"><div className="section-heading"><h2>Tài khoản</h2><span>Tổng cộng {page.total}</span></div><div className="admin-table-wrap"><table><thead><tr><th>Người dùng</th><th>Trạng thái</th><th>Vai trò</th><th>Cuộc trò chuyện</th><th>Yêu cầu</th><th>Ngày tham gia</th><th><span className="sr-only">Thao tác</span></th></tr></thead><tbody>{page.items.map((item) => <tr key={item.id}><td><strong>{item.display_name || "Chưa đặt tên"}</strong><span>{item.email}</span></td><td><span className={`status-label ${item.is_active ? "success" : "failed"}`}>{item.is_active ? "Đang hoạt động" : "Đã vô hiệu hoá"}</span></td><td>{item.is_admin ? "Quản trị viên" : "Người dùng"}</td><td>{item.conversation_count}</td><td>{item.run_count}</td><td>{new Date(item.created_at).toLocaleDateString("vi-VN")}</td><td><button className="text-button" disabled={item.id === currentUserId} onClick={() => onToggle(item)}>{item.is_active ? "Vô hiệu hoá" : "Kích hoạt"}</button></td></tr>)}</tbody></table></div></section>;
}

function RunsTable({ page }: { page: AdminAgentRunPage }) {
  return <section className="admin-section"><div className="section-heading"><h2>Yêu cầu gần đây</h2><span>Tổng cộng {page.total}</span></div><div className="admin-table-wrap"><table><thead><tr><th>Thời gian</th><th>Người dùng</th><th>Loại yêu cầu</th><th>Cách tra cứu</th><th>Trạng thái</th><th>Độ trễ</th><th>Công cụ</th></tr></thead><tbody>{page.items.map((run) => <tr key={run.id}><td>{new Date(run.created_at).toLocaleString("vi-VN")}</td><td><strong>{run.user_display_name || run.user_email}</strong><span>{run.user_email}</span></td><td>{intentLabel(run.intent)}</td><td>{retrievalModeLabel(run.retrieval_mode)}</td><td><span className={`status-label ${run.status}`}>{runStatusLabel(run.status)}</span></td><td>{run.latency_ms === null ? "-" : `${run.latency_ms} ms`}</td><td>{run.tools_used?.map(toolLabel).join(", ") || "-"}</td></tr>)}</tbody></table></div></section>;
}

function intentLabel(intent: string | null) {
  if (!intent) return "-";
  return ({ FACTUAL: "Thông tin điểm đến", ITINERARY: "Lịch trình", COMPARISON: "So sánh", CURRENT_INFO: "Thông tin hiện tại", OUT_OF_SCOPE: "Ngoài phạm vi" } as Record<string, string>)[intent] || "Chưa phân loại";
}

function retrievalModeLabel(mode: string | null) {
  if (!mode) return "-";
  return ({ RAG_ONLY: "Kho tri thức", WEB_FIRST: "Ưu tiên nguồn trực tuyến", MIXED: "Kết hợp", NO_RETRIEVAL: "Không cần tra cứu" } as Record<string, string>)[mode] || "Chưa xác định";
}

function runStatusLabel(status: string) {
  return ({ running: "Đang xử lý", success: "Thành công", degraded: "Hoàn thành một phần", failed: "Thất bại" } as Record<string, string>)[status] || "Chưa xác định";
}

function toolLabel(tool: string) {
  return ({ weather: "Thời tiết", search_travel_knowledge: "Kho tri thức du lịch", web_search: "Tìm kiếm trực tuyến", routing: "Đường đi", map_location: "Địa điểm", budget_calculator: "Ước tính chi phí", distance_matrix: "So sánh khoảng cách" } as Record<string, string>)[tool] || "Công cụ khác";
}
