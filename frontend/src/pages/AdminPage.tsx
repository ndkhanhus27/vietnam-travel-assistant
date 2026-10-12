import { useCallback, useEffect, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import {
  BookOutlined, CommentOutlined, MenuOutlined, MoonOutlined, PlusOutlined,
  ReloadOutlined, RobotOutlined, SearchOutlined, SunOutlined, TeamOutlined,
} from "@ant-design/icons";
import { Button, Empty, Input, Pagination, Select, Spin, Switch, Tooltip } from "antd";
import { api, ApiError } from "../api/client";
import type {
  AdminAgentRun, AdminAgentRunPage, AdminConversation, AdminConversationDetail,
  AdminConversationPage, AdminKnowledge, AdminOverview, AdminUser, AdminUserPage,
} from "../api/types";
import { useAppearance } from "../appearance/AppearanceProvider";
import { useAuth } from "../auth/AuthProvider";
import { useLocale } from "../locale/LocaleProvider";
import { localizeNotification } from "../locale/notifications";

type View = "users" | "conversations" | "runs" | "knowledge";
type Translate = (vi: string, en: string) => string;
const PAGE_SIZE = 20;

export function AdminPage() {
  const { user } = useAuth();
  const { language, t } = useLocale();
  const { resolvedMode, setMode } = useAppearance();
  const [view, setView] = useState<View>("users");
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [users, setUsers] = useState<AdminUserPage | null>(null);
  const [conversations, setConversations] = useState<AdminConversationPage | null>(null);
  const [runs, setRuns] = useState<AdminAgentRunPage | null>(null);
  const [knowledge, setKnowledge] = useState<AdminKnowledge | null>(null);
  const [selectedConversation, setSelectedConversation] = useState<AdminConversationDetail | null>(null);
  const [selectedRun, setSelectedRun] = useState<AdminAgentRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [page, setPage] = useState(1);
  const [draftQuery, setDraftQuery] = useState("");
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const options = compactFilters({ q: query, ...filters });
      const overviewRequest = api.adminOverview();
      if (view === "users") setUsers(await api.adminUsers(PAGE_SIZE, (page - 1) * PAGE_SIZE, options));
      if (view === "conversations") setConversations(await api.adminConversations(PAGE_SIZE, (page - 1) * PAGE_SIZE, options));
      if (view === "runs") setRuns(await api.adminAgentRuns(PAGE_SIZE, (page - 1) * PAGE_SIZE, options));
      if (view === "knowledge") setKnowledge(await api.adminKnowledge());
      setOverview(await overviewRequest);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : t("Không thể tải dữ liệu quản trị.", "Could not load admin data."));
    } finally {
      setLoading(false);
    }
  }, [filters, page, query, t, view]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    setPage(1);
    setDraftQuery("");
    setQuery("");
    setFilters({});
    setSelectedConversation(null);
    setSelectedRun(null);
  }, [view]);

  if (!user) return null;
  if (!user.is_admin) return <Navigate to="/" replace />;

  async function toggleUser(item: AdminUser) {
    try {
      const updated = await api.updateAdminUser(item.id, !item.is_active);
      setUsers((current) => current && ({
        ...current,
        items: current.items.map((entry) => entry.id === updated.id ? updated : entry),
      }));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : t("Không thể cập nhật người dùng.", "Could not update this user."));
    }
  }

  async function openConversation(item: AdminConversation) {
    setLoading(true);
    try {
      setSelectedConversation(await api.adminConversation(item.id));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : t("Không thể mở hội thoại.", "Could not open this conversation."));
    } finally {
      setLoading(false);
    }
  }

  const nav: Array<{ value: View; icon: React.ReactNode; vi: string; en: string }> = [
    { value: "users", icon: <TeamOutlined />, vi: "Người dùng", en: "Users" },
    { value: "conversations", icon: <CommentOutlined />, vi: "Hội thoại", en: "Conversations" },
    { value: "runs", icon: <RobotOutlined />, vi: "Lượt chạy AI", en: "AI Runs" },
    { value: "knowledge", icon: <BookOutlined />, vi: "Kho tri thức", en: "Knowledge Base" },
  ];
  const descriptions: Record<View, [string, string]> = {
    users: ["Quản lý tài khoản và quyền truy cập", "Manage accounts and access"],
    conversations: ["Theo dõi và kiểm tra lịch sử hội thoại", "Review conversation history"],
    runs: ["Theo dõi workflow, công cụ và lỗi vận hành", "Monitor workflows, tools, and failures"],
    knowledge: ["Theo dõi corpus PostgreSQL và Qdrant", "Monitor the PostgreSQL corpus and Qdrant"],
  };
  const currentNav = nav.find((item) => item.value === view)!;
  const total = view === "users" ? users?.total : view === "conversations" ? conversations?.total : runs?.total;

  return <main className="admin-page">
    <aside className="admin-sidebar">
      <div className="admin-brand"><span>Vietnam Travel Advisor</span><MenuOutlined /></div>
      <Link className="admin-new-chat" to="/"><PlusOutlined />{t("Cuộc trò chuyện mới", "New conversation")}</Link>
      <section className="admin-nav-section">
        <div className="admin-nav-label">CHAT</div>
        <Link className="admin-chat-link" to="/"><CommentOutlined />{t("Cuộc trò chuyện", "Conversations")}</Link>
      </section>
      <section className="admin-nav-section">
        <div className="admin-nav-label">ADMIN</div>
        <nav aria-label={t("Điều hướng quản trị", "Admin navigation")}>
          {nav.map((item) => <button key={item.value} aria-label={t(item.vi, item.en)} className={view === item.value ? "is-active" : ""} onClick={() => setView(item.value)}>{item.icon}<span>{t(item.vi, item.en)}</span></button>)}
        </nav>
      </section>
      <div className="admin-profile"><span className="avatar">{(user.display_name || user.email).slice(0, 1).toUpperCase()}</span><span><strong>{user.display_name || t("Quản trị viên", "Administrator")}</strong><small>{user.email}</small></span></div>
    </aside>

    <section className="admin-content">
      <header className="admin-header">
        <div><h1>{t(currentNav.vi, currentNav.en)}</h1><p>{t(...descriptions[view])}</p></div>
        <div className="admin-header-actions">
          <Tooltip title={resolvedMode === "dark" ? t("Chế độ sáng", "Light mode") : t("Chế độ tối", "Dark mode")}><Button shape="circle" icon={resolvedMode === "dark" ? <SunOutlined /> : <MoonOutlined />} onClick={() => setMode(resolvedMode === "dark" ? "light" : "dark")} /></Tooltip>
          <Button icon={<ReloadOutlined />} onClick={() => void load()}>{t("Làm mới", "Refresh")}</Button>
        </div>
      </header>

      {error && <div className="inline-error" role="alert">{localizeNotification(error)}</div>}
      <Spin spinning={loading}>
        {view === "users" && overview && <AdminMetrics items={[
          [t("Tổng người dùng", "Total users"), overview.total_users],
          [t("Đang hoạt động", "Active users"), overview.active_users],
          [t("Đã chặn", "Blocked users"), Math.max(0, overview.total_users - overview.active_users)],
        ]} />}
        {view === "runs" && overview && <AdminMetrics items={[
          [t("Lượt chạy hôm nay", "Runs today"), overview.requests_today],
          [t("Tỉ lệ thành công", "Success rate"), overview.total_runs ? `${((overview.successful_runs / overview.total_runs) * 100).toFixed(1)}%` : "-"],
          [t("Độ trễ trung bình", "Average latency"), overview.average_latency_ms === null ? "-" : `${(overview.average_latency_ms / 1000).toFixed(1)}s`],
        ]} />}

        {view !== "knowledge" && <AdminToolbar view={view} draftQuery={draftQuery} setDraftQuery={setDraftQuery} onSearch={() => { setPage(1); setQuery(draftQuery.trim()); }} filters={filters} setFilters={(next) => { setPage(1); setFilters(next); }} t={t} />}
        {!loading && view === "users" && users && <UsersTable page={users} currentUserId={user.id} onToggle={toggleUser} language={language} t={t} />}
        {!loading && view === "conversations" && conversations && <ConversationsTable page={conversations} selected={selectedConversation} onOpen={openConversation} language={language} t={t} />}
        {!loading && view === "runs" && runs && <RunsTable page={runs} selected={selectedRun} onSelect={setSelectedRun} language={language} t={t} />}
        {!loading && view === "knowledge" && knowledge && <Knowledge data={knowledge} language={language} t={t} />}
      </Spin>
      {(view === "users" || view === "conversations" || view === "runs") && <Pagination className="admin-pagination" current={page} pageSize={PAGE_SIZE} total={total} showSizeChanger={false} onChange={setPage} />}
    </section>
  </main>;
}

function compactFilters(filters: Record<string, string>) {
  return Object.fromEntries(Object.entries(filters).filter(([, value]) => value));
}

function AdminMetrics({ items }: { items: Array<[string, string | number]> }) {
  return <div className="admin-metric-grid">{items.map(([label, value]) => <div className="admin-metric-card" key={label}><span>{label}</span><strong>{value}</strong></div>)}</div>;
}

function AdminToolbar({ view, draftQuery, setDraftQuery, onSearch, filters, setFilters, t }: { view: Exclude<View, "knowledge">; draftQuery: string; setDraftQuery: (value: string) => void; onSearch: () => void; filters: Record<string, string>; setFilters: (value: Record<string, string>) => void; t: Translate }) {
  const set = (key: string, value: string) => setFilters({ ...filters, [key]: value });
  return <section className="admin-toolbar-card">
    <div className="admin-card-head"><h2>{view === "users" ? t("Quản lý người dùng", "User Management") : view === "conversations" ? t("Quản lý hội thoại", "Conversation Management") : t("Lượt chạy AI", "AI / Agent Runs")}</h2></div>
    <div className="admin-toolbar">
      <Input allowClear prefix={<SearchOutlined />} value={draftQuery} onChange={(event) => setDraftQuery(event.target.value)} onPressEnter={onSearch} placeholder={view === "users" ? t("Tìm theo email hoặc tên", "Search by email or name") : view === "conversations" ? t("Tìm hội thoại hoặc chủ sở hữu", "Search conversation or owner") : t("Tìm user, hội thoại hoặc run ID", "Search user, conversation, or run ID")} />
      {view === "users" && <><Select allowClear placeholder={t("Tất cả vai trò", "All roles")} value={filters.role || undefined} onChange={(value) => set("role", value || "")} options={[{ value: "admin", label: "Admin" }, { value: "user", label: "User" }]} /><Select allowClear placeholder={t("Mọi phương thức", "All providers")} value={filters.provider || undefined} onChange={(value) => set("provider", value || "")} options={[{ value: "google", label: "Google" }, { value: "local", label: t("Mật khẩu", "Password") }]} /><Select allowClear placeholder={t("Mọi trạng thái", "All status")} value={filters.status || undefined} onChange={(value) => set("status", value || "")} options={[{ value: "active", label: t("Hoạt động", "Active") }, { value: "blocked", label: t("Đã chặn", "Blocked") }]} /></>}
      {view === "runs" && <><Select allowClear placeholder="Intent" value={filters.intent || undefined} onChange={(value) => set("intent", value || "")} options={["FACTUAL", "ITINERARY", "COMPARISON", "CURRENT_INFO", "OUT_OF_SCOPE"].map((value) => ({ value, label: value }))} /><Select allowClear placeholder={t("Mọi chế độ", "All modes")} value={filters.retrieval_mode || undefined} onChange={(value) => set("retrieval_mode", value || "")} options={["RAG_ONLY", "WEB_FIRST", "MIXED", "NO_RETRIEVAL"].map((value) => ({ value, label: value }))} /><Select allowClear placeholder={t("Mọi trạng thái", "All status")} value={filters.status || undefined} onChange={(value) => set("status", value || "")} options={["success", "degraded", "failed", "running"].map((value) => ({ value, label: runStatusLabel(value, t) }))} /></>}
      <Button type="primary" icon={<SearchOutlined />} onClick={onSearch}>{t("Tìm", "Search")}</Button>
    </div>
  </section>;
}

function UsersTable({ page, currentUserId, onToggle, language, t }: { page: AdminUserPage; currentUserId: string; onToggle: (user: AdminUser) => void; language: string; t: Translate }) {
  return <section className="admin-data-card"><div className="admin-table-wrap"><table><thead><tr><th>{t("Người dùng", "User")}</th><th>Email</th><th>{t("Phương thức", "Provider")}</th><th>{t("Vai trò", "Role")}</th><th>{t("Trạng thái", "Status")}</th><th>{t("Ngày tạo", "Created")}</th><th>{t("Đăng nhập cuối", "Last login")}</th><th /></tr></thead><tbody>{page.items.map((item) => <tr key={item.id}><td><strong>{item.display_name || t("Chưa đặt tên", "Unnamed")}</strong></td><td>{item.email}</td><td>{item.providers.map((value) => value === "local" ? t("Mật khẩu", "Password") : "Google").join(" + ") || "-"}</td><td><span className="admin-badge">{item.is_admin ? "Admin" : "User"}</span></td><td><span className={`admin-badge ${item.is_active ? "ok" : "warn"}`}>{item.is_active ? t("Hoạt động", "Active") : t("Đã chặn", "Blocked")}</span></td><td>{formatDate(item.created_at, language)}</td><td>{item.last_login_at ? formatDate(item.last_login_at, language, true) : "-"}</td><td><Tooltip title={item.id === currentUserId ? t("Không thể khoá chính bạn", "You cannot block yourself") : ""}><Switch size="small" checked={item.is_active} disabled={item.id === currentUserId} onChange={() => void onToggle(item)} /></Tooltip></td></tr>)}</tbody></table></div></section>;
}

function ConversationsTable({ page, selected, onOpen, language, t }: { page: AdminConversationPage; selected: AdminConversationDetail | null; onOpen: (item: AdminConversation) => void; language: string; t: Translate }) {
  return <><section className="admin-data-card"><div className="admin-table-wrap"><table><thead><tr><th>{t("Hội thoại", "Conversation")}</th><th>{t("Chủ sở hữu", "Owner")}</th><th>Messages</th><th>Agent Runs</th><th>{t("Ngày tạo", "Created")}</th><th>{t("Cập nhật", "Updated")}</th><th /></tr></thead><tbody>{page.items.map((item) => <tr key={item.id}><td><strong>{item.title || t("Cuộc trò chuyện mới", "New conversation")}</strong><span>{item.id}</span></td><td>{item.user_display_name || item.user_email}</td><td>{item.message_count}</td><td>{item.run_count}</td><td>{formatDate(item.created_at, language)}</td><td>{formatDate(item.last_message_at || item.updated_at, language, true)}</td><td><Button type="link" onClick={() => void onOpen(item)}>{t("Mở", "Open")} →</Button></td></tr>)}</tbody></table></div></section>{selected && <div className="admin-detail-grid"><section className="admin-data-card conversation-preview"><div className="admin-card-head"><h2>{t("Nội dung hội thoại", "Conversation Preview")}</h2><span className="admin-badge">{selected.message_count} messages</span></div><div className="admin-panel-body">{selected.messages.length ? selected.messages.map((message) => <article key={message.id} className={`admin-message ${message.role}`}><div><strong>{message.role === "assistant" ? "Assistant" : message.role === "user" ? "User" : "System"}</strong><time>{formatDate(message.created_at, language, true)}</time></div><p>{message.content}</p></article>) : <Empty description={t("Hội thoại chưa có tin nhắn", "No messages in this conversation")} />}</div></section><Metadata data={selected} t={t} /></div>}</>;
}

function Metadata({ data, t }: { data: AdminConversationDetail; t: Translate }) {
  return <section className="admin-data-card admin-metadata"><div className="admin-card-head"><h2>{t("Thông tin hội thoại", "Conversation Metadata")}</h2></div><dl><div><dt>{t("Chủ sở hữu", "Owner")}</dt><dd>{data.user_email}</dd></div><div><dt>Messages</dt><dd>{data.message_count}</dd></div><div><dt>Agent runs</dt><dd>{data.run_count}</dd></div><div><dt>Intent</dt><dd>{data.last_intent || "-"}</dd></div><div><dt>Mode</dt><dd>{data.last_retrieval_mode || "-"}</dd></div></dl></section>;
}

function RunsTable({ page, selected, onSelect, language, t }: { page: AdminAgentRunPage; selected: AdminAgentRun | null; onSelect: (run: AdminAgentRun) => void; language: string; t: Translate }) {
  return <><section className="admin-data-card"><div className="admin-table-wrap"><table><thead><tr><th>Run</th><th>{t("Người dùng", "User")}</th><th>Intent</th><th>Mode</th><th>Tools</th><th>Grounded</th><th>{t("Độ trễ", "Latency")}</th><th>{t("Trạng thái", "Status")}</th><th>{t("Thời gian", "Created")}</th></tr></thead><tbody>{page.items.map((run) => <tr key={run.id} className={selected?.id === run.id ? "is-selected" : ""} onClick={() => onSelect(run)}><td><strong>{run.id.slice(0, 8)}...</strong></td><td>{run.user_display_name || run.user_email}</td><td><span className="admin-badge">{run.intent || "-"}</span></td><td>{run.retrieval_mode || "-"}</td><td>{run.tools_used?.map((tool) => toolLabel(tool, t)).join(", ") || "-"}</td><td>{run.grounded ? t("Có", "Yes") : t("Không", "No")}</td><td>{run.latency_ms === null ? "-" : `${(run.latency_ms / 1000).toFixed(1)}s`}</td><td><span className={`admin-badge ${run.status === "success" ? "ok" : run.status === "failed" ? "bad" : "warn"}`}>{runStatusLabel(run.status, t)}</span></td><td>{formatDate(run.created_at, language, true)}</td></tr>)}</tbody></table></div></section>{selected && <RunDetails run={selected} t={t} />}</>;
}

function RunDetails({ run, t }: { run: AdminAgentRun; t: Translate }) {
  return <div className="admin-detail-grid"><section className="admin-data-card admin-metadata"><div className="admin-card-head"><h2>{t("Tóm tắt lượt chạy", "Selected Run Summary")}</h2></div><dl><div><dt>Intent</dt><dd>{run.intent || "-"}</dd></div><div><dt>Mode</dt><dd>{run.retrieval_mode || "-"}</dd></div><div><dt>Evidence</dt><dd>{run.evidence_count}</dd></div><div><dt>Citations</dt><dd>{run.citation_count}</dd></div><div><dt>{t("Trạng thái", "Status")}</dt><dd><span className={`admin-badge ${run.status === "success" ? "ok" : run.status === "failed" ? "bad" : "warn"}`}>{runStatusLabel(run.status, t)}</span></dd></div></dl></section><section className="admin-data-card"><div className="admin-card-head"><h2>{t("Công cụ đã dùng", "Tools Used")}</h2></div><div className="admin-panel-body admin-tool-list">{run.tools_used?.length ? run.tools_used.map((tool, index) => <div key={`${tool}-${index}`}><span>{index + 1}</span><strong>{toolLabel(tool, t)}</strong></div>) : <Empty description={t("Không dùng công cụ", "No tools used")} />}</div></section></div>;
}

function Knowledge({ data, language, t }: { data: AdminKnowledge; language: string; t: Translate }) {
  const healthy = data.qdrant_status !== "unavailable";
  return <><div className="knowledge-metrics"><div className="admin-metric-card"><span>Documents</span><strong>{data.documents}</strong><small>PostgreSQL</small></div><div className="admin-metric-card"><span>Entity candidates</span><strong>{data.entity_candidates.toLocaleString()}</strong><small>PostgreSQL</small></div><div className="admin-metric-card"><span>Qdrant points</span><strong>{data.points ?? "-"}</strong><small>{data.collection}</small></div><div className="admin-metric-card"><span>Embedding</span><strong>{data.vector_size ?? "-"}</strong><small>{data.distance || "-"}</small></div></div><div className="admin-detail-grid"><KnowledgePanel title={t("Trạng thái corpus", "Corpus Status")} badge={t("Hoạt động", "Healthy")} rows={[["Documents", data.documents], ["Entity candidates", data.entity_candidates], [t("Lần nhập gần nhất", "Last import"), data.last_import_at ? formatDate(data.last_import_at, language, true) : "-"]]} /><KnowledgePanel title="Qdrant Collection" badge={data.qdrant_status} healthy={healthy} rows={[["Collection", data.collection], ["Points", data.points ?? "-"], ["Vector size", data.vector_size ?? "-"], ["Distance", data.distance || "-"]]} /></div></>;
}

function KnowledgePanel({ title, badge, rows, healthy = true }: { title: string; badge: string; rows: Array<[string, string | number]>; healthy?: boolean }) {
  return <section className="admin-data-card admin-metadata"><div className="admin-card-head"><h2>{title}</h2><span className={`admin-badge ${healthy ? "ok" : "bad"}`}>{badge}</span></div><dl>{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl></section>;
}

function runStatusLabel(status: string, t: Translate) {
  return ({ running: t("Đang xử lý", "Running"), success: t("Thành công", "Success"), degraded: t("Một phần", "Degraded"), failed: t("Thất bại", "Failed") } as Record<string, string>)[status] || status;
}

function toolLabel(tool: string, t: Translate) {
  return ({ weather: t("Thời tiết", "Weather"), search_travel_knowledge: t("Kho tri thức", "Knowledge search"), web_search: t("Tìm kiếm web", "Web search"), routing: t("Đường đi", "Routing"), map_location: t("Địa điểm", "Location"), distance_matrix: t("Khoảng cách", "Distance") } as Record<string, string>)[tool] || tool;
}

function formatDate(value: string, language: string, time = false) {
  return new Intl.DateTimeFormat(language === "vi" ? "vi-VN" : "en-US", time ? { dateStyle: "short", timeStyle: "short" } : { dateStyle: "short" }).format(new Date(value));
}
