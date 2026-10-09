import { FormEvent, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { reconcileCompletedMessages } from "../api/chatState";
import type { AgentProgressStage, CitationResponse, ConversationResponse, MessageResponse, UserResponse } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { appearanceOptions, useAppearance } from "../appearance/AppearanceProvider";
import { MarkdownLite } from "../components/MarkdownLite";
import { Modal } from "../components/Modal";
import {
  ArchiveIcon, ChatIcon, CheckIcon, EditIcon, ExternalIcon, LogoutIcon, MenuIcon,
  MoreIcon, PlusIcon, SendIcon, SettingsIcon, TrashIcon, UsersIcon, WarningIcon,
} from "../components/Icons";

const suggestions = [
  "Lên lịch trình khám phá thiên nhiên Đà Lạt trong 3 ngày",
  "Gợi ý điểm đến phù hợp cho chuyến đi hai người",
  "So sánh Huế và Hội An cho kỳ nghỉ ngắn ngày",
  "Ngày mai Đà Nẵng có mưa không?",
];

const progressLabels: Record<AgentProgressStage, string> = {
  planning: "Đang phân tích yêu cầu",
  retrieving: "Đang tìm thông tin du lịch",
  validating: "Đang kiểm tra nguồn",
  reasoning: "Đang tổng hợp thông tin",
  generating: "Đang soạn câu trả lời",
};

const toolLabels: Record<string, string> = {
  weather: "Đang kiểm tra thời tiết",
  search_travel_knowledge: "Đang tra cứu thông tin du lịch",
  web_search: "Đang tìm thông tin mới nhất",
  routing: "Đang tính đường đi",
  map_location: "Đang xác định địa điểm",
  budget_calculator: "Đang ước tính chi phí",
  distance_matrix: "Đang so sánh khoảng cách",
};

function titleOf(conversation: ConversationResponse) {
  return conversation.title || "Cuộc trò chuyện mới";
}

function groupConversations(conversations: ConversationResponse[]) {
  return { today: conversations.slice(0, 2), previous: conversations.slice(2) };
}

function sortMessages(messages: MessageResponse[]) {
  return [...messages].sort((a, b) => a.sequence_no - b.sequence_no);
}

export function createOptimisticMessageId() {
  const randomUUID = globalThis.crypto?.randomUUID;
  const uniquePart = typeof randomUUID === "function"
    ? randomUUID.call(globalThis.crypto)
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `optimistic-${uniquePart}`;
}

export function consumePendingConversationNavigation(
  pending: { current: string | null },
  conversationId: string | undefined,
) {
  if (!conversationId || pending.current !== conversationId) return false;
  pending.current = null;
  return true;
}

export function TravelChatPage() {
  const { conversationId } = useParams();
  const navigate = useNavigate();
  const { user, logout, updateUser } = useAuth();
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [desktopCollapsed, setDesktopCollapsed] = useState(false);
  const [conversations, setConversations] = useState<ConversationResponse[]>([]);
  const [messages, setMessages] = useState<MessageResponse[]>([]);
  const [degradedIds, setDegradedIds] = useState<Set<string>>(new Set());
  const [listLoading, setListLoading] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [pageError, setPageError] = useState("");
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const [activeMenu, setActiveMenu] = useState<string | null>(null);
  const [renameTarget, setRenameTarget] = useState<ConversationResponse | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ConversationResponse | null>(null);
  const [archivedOpen, setArchivedOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [rateLimitSeconds, setRateLimitSeconds] = useState<number | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const viewRef = useRef<HTMLElement>(null);
  const stayAtBottom = useRef(true);
  const pendingConversationNavigation = useRef<string | null>(null);

  const activeConversation = conversations.find((item) => item.id === conversationId);
  const visible = useMemo(() => conversations.filter((item) => !item.is_archived), [conversations]);
  const groups = useMemo(() => groupConversations(visible), [visible]);
  const archived = conversations.filter((item) => item.is_archived);

  const loadConversations = useCallback(async (includeArchived = false) => {
    const result = await api.listConversations(includeArchived);
    setConversations(result);
    return result;
  }, []);

  const handleApiError = useCallback((cause: unknown, fallback: string) => {
    if (cause instanceof ApiError) {
      if (cause.status === 429) setRateLimitSeconds(cause.retryAfter || 60);
      else setPageError(cause.status === 422 ? fallback : cause.message || fallback);
    } else setPageError(fallback);
  }, []);

  useEffect(() => {
    let active = true;
    setListLoading(true);
    loadConversations().catch((cause) => active && handleApiError(cause, "Không thể tải danh sách cuộc trò chuyện."))
      .finally(() => active && setListLoading(false));
    return () => { active = false; };
  }, [handleApiError, loadConversations]);

  const loadHistory = useCallback(async (id: string) => {
    setHistoryLoading(true);
    try {
      const history = await api.getMessages(id);
      setMessages(sortMessages(history));
      setPageError("");
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 404) {
        setConversations((current) => current.filter((item) => item.id !== id));
        setMessages([]);
        navigate("/", { replace: true });
      } else handleApiError(cause, "Không thể tải lịch sử trò chuyện.");
    } finally {
      setHistoryLoading(false);
    }
  }, [handleApiError, navigate]);

  useEffect(() => {
    setActiveMenu(null);
    setUserMenuOpen(false);
    setPageError("");
    if (!conversationId) {
      setMessages([]);
      return;
    }
    if (consumePendingConversationNavigation(pendingConversationNavigation, conversationId)) return;
    setMessages([]);
    void (async () => {
      if (!conversations.some((item) => item.id === conversationId)) {
        try {
          const conversation = await api.getConversation(conversationId);
          setConversations((current) => [conversation, ...current.filter((item) => item.id !== conversation.id)]);
        } catch (cause) {
          if (cause instanceof ApiError && cause.status === 404) navigate("/", { replace: true });
          else handleApiError(cause, "Không thể mở cuộc trò chuyện này.");
          return;
        }
      }
      await loadHistory(conversationId);
    })();
  }, [conversationId]); // Conversation selection is the intended reload boundary.

  useEffect(() => {
    if (rateLimitSeconds === null) return;
    const timer = window.setInterval(() => setRateLimitSeconds((value) => value && value > 1 ? value - 1 : null), 1000);
    return () => window.clearInterval(timer);
  }, [rateLimitSeconds]);

  useEffect(() => {
    if (stayAtBottom.current) viewRef.current?.scrollTo({ top: viewRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, progress]);

  async function newChat() {
    if (sending) return;
    setPageError("");
    try {
      const conversation = await api.createConversation();
      setConversations((current) => [conversation, ...current]);
      setMessages([]);
      navigate(`/c/${conversation.id}`);
      setMobileSidebarOpen(false);
    } catch (cause) {
      handleApiError(cause, "Không thể tạo cuộc trò chuyện mới.");
    }
  }

  async function send(text = draft) {
    const value = text.trim();
    if (!value || sending || rateLimitSeconds !== null) return;
    setSending(true);
    setPageError("");
    let id = conversationId;
    try {
      if (!id) {
        const created = await api.createConversation();
        id = created.id;
        setConversations((current) => [created, ...current]);
        pendingConversationNavigation.current = id;
        navigate(`/c/${id}`);
      }
      const optimisticId = createOptimisticMessageId();
      const optimistic: MessageResponse = {
        id: optimisticId, role: "user", content: value, sequence_no: Number.MAX_SAFE_INTEGER,
        intent: null, citations: null, warnings: null, created_at: new Date().toISOString(),
      };
      setMessages((current) => [...current, optimistic]);
      setDraft("");
      setProgress(progressLabels.planning);
      let streamError: string | null = null;

      await api.streamMessage(id, value, (event) => {
        if (event.event === "connected") return;
        if (event.event === "stage") setProgress(progressLabels[event.data.stage]);
        if (event.event === "tool" && event.data.status === "started") setProgress(toolLabels[event.data.tool] || "Đang thu thập thông tin du lịch");
        if (event.event === "error") streamError = event.data.message || "Trợ lý chưa thể hoàn tất yêu cầu này.";
        if (event.event === "completed") {
          const result = event.data;
          setMessages((current) => reconcileCompletedMessages(current, optimisticId, result));
          if (result.agent_run.status === "degraded") setDegradedIds((current) => new Set(current).add(result.assistant_message.id));
        }
      });
      if (streamError) {
        setPageError(streamError);
        await loadHistory(id);
      } else {
        await loadConversations();
      }
    } catch (cause) {
      handleApiError(cause, "Kết nối bị gián đoạn. Lịch sử trò chuyện đã được cập nhật lại.");
      if (id) await loadHistory(id);
    } finally {
      setProgress(null);
      setSending(false);
      textareaRef.current?.focus();
    }
  }

  async function renameConversation(title: string) {
    if (!renameTarget) return;
    try {
      const updated = await api.updateConversation(renameTarget.id, { title: title.trim() });
      setConversations((current) => current.map((item) => item.id === updated.id ? updated : item));
      setRenameTarget(null);
    } catch (cause) { handleApiError(cause, "Không thể đổi tên cuộc trò chuyện."); }
  }

  async function archiveConversation(id: string, isArchived = true) {
    try {
      const updated = await api.updateConversation(id, { is_archived: isArchived });
      setConversations((current) => current.map((item) => item.id === id ? updated : item));
      setActiveMenu(null);
      if (conversationId === id && isArchived) navigate("/");
    } catch (cause) { handleApiError(cause, "Không thể cập nhật cuộc trò chuyện."); }
  }

  async function deleteConversation(id: string) {
    try {
      await api.deleteConversation(id);
      setConversations((current) => current.filter((item) => item.id !== id));
      setDeleteTarget(null);
      if (conversationId === id) { setMessages([]); navigate("/"); }
    } catch (cause) { handleApiError(cause, "Không thể xoá cuộc trò chuyện."); }
  }

  async function openArchived() {
    setUserMenuOpen(false);
    try { await loadConversations(true); setArchivedOpen(true); }
    catch (cause) { handleApiError(cause, "Không thể tải các cuộc trò chuyện đã lưu trữ."); }
  }

  const displayName = user?.display_name || user?.email || "Tài khoản";
  const initial = displayName.slice(0, 1).toUpperCase();

  return (
    <div className={`app-shell ${desktopCollapsed ? "sidebar-collapsed" : ""}`}>
      <aside className={`sidebar ${mobileSidebarOpen ? "is-open" : ""}`} aria-label="Lịch sử trò chuyện">
        <div className="sidebar-head">
          <div className="sidebar-title-row">
            <Link className="brand" to="/"><span className="brand-full">Vietnam Travel Advisor</span><span className="brand-short">VTA</span></Link>
            <button className="sidebar-toggle-button" onClick={() => { if (window.matchMedia("(max-width: 760px)").matches) setMobileSidebarOpen(false); else setDesktopCollapsed((value) => !value); }} aria-label="Thu gọn hoặc mở rộng thanh bên"><MenuIcon /></button>
          </div>
          <button className="new-chat-button" onClick={newChat} disabled={sending}><PlusIcon /><span>Cuộc trò chuyện mới</span></button>
        </div>
        <nav className="conversation-nav" aria-label="Danh sách cuộc trò chuyện">
          {listLoading && <div className="history-skeleton"><span /><span /><span /></div>}
          {!listLoading && !visible.length && <p className="empty-dialog-copy">Chưa có cuộc trò chuyện nào.</p>}
          <ConversationGroup title="Hôm nay" items={groups.today} activeId={conversationId} activeMenu={activeMenu} setActiveMenu={setActiveMenu} setRenameTarget={setRenameTarget} setDeleteTarget={setDeleteTarget} archiveConversation={archiveConversation} />
          <ConversationGroup title="Trước đó" items={groups.previous} activeId={conversationId} activeMenu={activeMenu} setActiveMenu={setActiveMenu} setRenameTarget={setRenameTarget} setDeleteTarget={setDeleteTarget} archiveConversation={archiveConversation} />
        </nav>
        <div className="sidebar-user">
          <button className="user-row" onClick={() => setUserMenuOpen((value) => !value)} aria-expanded={userMenuOpen}><span className="avatar">{initial}</span><span>{displayName}</span><MoreIcon className="user-more" /></button>
          {userMenuOpen && <div className="user-menu">
            <button onClick={() => { setSettingsOpen(true); setUserMenuOpen(false); }}><SettingsIcon />Cài đặt</button>
            <button onClick={openArchived}><ArchiveIcon />Cuộc trò chuyện đã lưu trữ</button>
            {user?.is_admin && <button onClick={() => navigate("/admin")}><UsersIcon />Trang quản trị</button>}
            <button onClick={async () => { try { await logout(); } finally { navigate("/login"); } }}><LogoutIcon />Đăng xuất</button>
          </div>}
        </div>
      </aside>
      {mobileSidebarOpen && <button className="mobile-backdrop" onClick={() => setMobileSidebarOpen(false)} aria-label="Đóng thanh bên" />}
      <main className="chat-main">
        <header className="mobile-header"><button className="icon-button" onClick={() => setMobileSidebarOpen(true)} aria-label="Mở thanh bên"><MenuIcon /></button><span>Vietnam Travel Advisor</span><span className="mobile-header-spacer" /></header>
        {!conversationId ? <EmptyState onSuggestion={send} /> : activeConversation || historyLoading ? (
          <section className="conversation-view" ref={viewRef} aria-label={activeConversation ? titleOf(activeConversation) : "Cuộc trò chuyện"} onScroll={(event) => { const element = event.currentTarget; stayAtBottom.current = element.scrollHeight - element.scrollTop - element.clientHeight < 120; }}>
            <div className="message-list">
              {historyLoading && !messages.length && <div className="history-skeleton"><span /><span /><span /></div>}
              {messages.map((message) => <MessageView key={message.id} message={message} degraded={degradedIds.has(message.id)} />)}
              {progress && <AgentProgress label={progress} />}
              {pageError && <div className="inline-error" role="alert">{pageError}</div>}
              {rateLimitSeconds !== null && <div className="inline-error" role="alert">Bạn thao tác quá nhanh. Vui lòng thử lại sau {rateLimitSeconds} giây.</div>}
            </div>
          </section>
        ) : <section className="center-state"><h1>Không tìm thấy cuộc trò chuyện</h1><p>Cuộc trò chuyện này không còn khả dụng.</p><button className="secondary-button" onClick={() => navigate("/")}>Bắt đầu cuộc trò chuyện mới</button></section>}
        <Composer draft={draft} setDraft={setDraft} onSubmit={(event) => { event.preventDefault(); void send(); }} loading={sending} blocked={rateLimitSeconds !== null} textareaRef={textareaRef} />
      </main>
      {renameTarget && <RenameDialog conversation={renameTarget} onClose={() => setRenameTarget(null)} onSave={renameConversation} />}
      {deleteTarget && <DeleteDialog conversation={deleteTarget} onClose={() => setDeleteTarget(null)} onDelete={() => deleteConversation(deleteTarget.id)} />}
      {archivedOpen && <ArchivedDialog conversations={archived} onClose={() => { setArchivedOpen(false); void loadConversations(); }} onUnarchive={(id) => archiveConversation(id, false)} onDelete={(item) => { setArchivedOpen(false); setDeleteTarget(item); }} />}
      {settingsOpen && user && <SettingsDialog user={user} onClose={() => setSettingsOpen(false)} onUserUpdated={updateUser} onLogoutAll={async () => { try { await api.logoutAll(); } finally { navigate("/login"); } }} />}
    </div>
  );
}

function ConversationGroup(props: { title: string; items: ConversationResponse[]; activeId?: string; activeMenu: string | null; setActiveMenu: (id: string | null) => void; setRenameTarget: (item: ConversationResponse) => void; setDeleteTarget: (item: ConversationResponse) => void; archiveConversation: (id: string) => void }) {
  if (!props.items.length) return null;
  return <section className="conversation-group"><div className="group-label">{props.title}</div>{props.items.map((item) => <ConversationRow key={item.id} item={item} active={props.activeId === item.id} menuOpen={props.activeMenu === item.id} setActiveMenu={props.setActiveMenu} setRenameTarget={props.setRenameTarget} setDeleteTarget={props.setDeleteTarget} archiveConversation={props.archiveConversation} />)}</section>;
}

function ConversationRow({ item, active, menuOpen, setActiveMenu, setRenameTarget, setDeleteTarget, archiveConversation }: { item: ConversationResponse; active: boolean; menuOpen: boolean; setActiveMenu: (id: string | null) => void; setRenameTarget: (item: ConversationResponse) => void; setDeleteTarget: (item: ConversationResponse) => void; archiveConversation: (id: string) => void }) {
  const buttonRef = useRef<HTMLButtonElement>(null);
  return <div className={`conversation-row ${active ? "is-active" : ""}`}>
    <Link to={`/c/${item.id}`}><ChatIcon /><span>{titleOf(item)}</span></Link>
    <button ref={buttonRef} className="row-menu-button" onClick={() => setActiveMenu(menuOpen ? null : item.id)} aria-expanded={menuOpen} aria-haspopup="menu" aria-label={`Tuỳ chọn cho ${titleOf(item)}`}><MoreIcon /></button>
    {menuOpen && <ConversationPopover anchorRef={buttonRef} onClose={() => setActiveMenu(null)}><button role="menuitem" onClick={() => { setRenameTarget(item); setActiveMenu(null); }}><EditIcon />Đổi tên</button><button role="menuitem" onClick={() => archiveConversation(item.id)}><ArchiveIcon />Lưu trữ</button><button role="menuitem" className="danger-text" onClick={() => { setDeleteTarget(item); setActiveMenu(null); }}><TrashIcon />Xoá</button></ConversationPopover>}
  </div>;
}

function ConversationPopover({ anchorRef, onClose, children }: { anchorRef: RefObject<HTMLButtonElement | null>; onClose: () => void; children: ReactNode }) {
  const [position, setPosition] = useState({ top: 0, left: 0 });
  useLayoutEffect(() => {
    const update = () => {
      const rect = anchorRef.current?.getBoundingClientRect();
      if (!rect) return;
      const width = 156;
      const height = 124;
      const left = Math.max(8, Math.min(window.innerWidth - width - 8, rect.right - width));
      const top = rect.bottom + 6 + height <= window.innerHeight ? rect.bottom + 6 : Math.max(8, rect.top - height - 6);
      setPosition({ top, left });
    };
    const closeOnEscape = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [anchorRef, onClose]);
  return createPortal(<div className="row-menu row-menu-portal" role="menu" style={position}>{children}</div>, document.body);
}

function EmptyState({ onSuggestion }: { onSuggestion: (text: string) => void }) {
  return <section className="empty-state"><div className="empty-copy"><div className="empty-kicker">Vietnam Travel Advisor</div><h1>Bạn muốn khám phá nơi nào ở Việt Nam?</h1><p>Hỏi về điểm đến, lịch trình, thời tiết, đường đi, chi phí hoặc so sánh các lựa chọn du lịch.</p></div><div className="suggestions" aria-label="Câu hỏi gợi ý">{suggestions.map((item) => <button key={item} onClick={() => onSuggestion(item)}>{item}</button>)}</div></section>;
}

export function MessageView({ message, degraded }: { message: MessageResponse; degraded: boolean }) {
  if (message.role === "user") return <article className="user-message"><div className="message-meta">Bạn</div><p>{message.content}</p></article>;
  return <article className="assistant-message"><div className="message-meta assistant-label">Vietnam Travel Advisor</div><MarkdownLite content={message.content} />{message.citations?.length ? <CitationList citations={message.citations} /> : null}{(degraded || message.warnings?.length) ? <div className="warning-row"><WarningIcon /><div>{message.warnings?.[0] || "Một số thông tin chưa thể được kiểm chứng đầy đủ."}</div></div> : null}</article>;
}

function CitationList({ citations }: { citations: CitationResponse[] }) {
  return <section className="citations" aria-label="Nguồn"><h3>Nguồn</h3><div className="citation-list">{citations.map((citation) => citation.url ? <a key={citation.citation_id} href={citation.url} target="_blank" rel="noreferrer"><span>[{citation.citation_id}]</span>{citation.title}<ExternalIcon /></a> : <div className="citation-static" key={citation.citation_id}><span>[{citation.citation_id}]</span>{citation.title}</div>)}</div></section>;
}

function AgentProgress({ label }: { label: string }) { return <div className="agent-progress" role="status" aria-live="polite"><span className="progress-dot" /><span>{label}...</span></div>; }

function Composer(props: { draft: string; setDraft: (value: string) => void; onSubmit: (event: FormEvent) => void; loading: boolean; blocked: boolean; textareaRef: RefObject<HTMLTextAreaElement | null> }) {
  useEffect(() => {
    const textarea = props.textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 144)}px`;
  }, [props.draft, props.textareaRef]);
  return <form className="composer-wrap" onSubmit={props.onSubmit}><div className="composer"><textarea ref={props.textareaRef} value={props.draft} onChange={(event) => props.setDraft(event.target.value.slice(0, 10000))} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} placeholder="Bạn muốn hỏi gì về chuyến đi?" rows={1} aria-label="Nội dung tin nhắn" disabled={props.loading || props.blocked} /><button className="send-button" disabled={!props.draft.trim() || props.loading || props.blocked} aria-label="Gửi"><SendIcon /></button></div><div className="character-count">{props.draft.length.toLocaleString("vi-VN")}/10.000</div></form>;
}

function RenameDialog({ conversation, onClose, onSave }: { conversation: ConversationResponse; onClose: () => void; onSave: (value: string) => void }) {
  const [value, setValue] = useState(titleOf(conversation));
  return <Modal title="Đổi tên cuộc trò chuyện" onClose={onClose}><form className="dialog-form" onSubmit={(event) => { event.preventDefault(); onSave(value); }}><label><span>Tên cuộc trò chuyện</span><input value={value} maxLength={255} onChange={(event) => setValue(event.target.value)} autoFocus /></label><div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose}>Huỷ</button><button className="primary-button" disabled={!value.trim()}>Lưu</button></div></form></Modal>;
}

function DeleteDialog({ conversation, onClose, onDelete }: { conversation: ConversationResponse; onClose: () => void; onDelete: () => void }) { return <Modal title="Xoá cuộc trò chuyện?" onClose={onClose}><p className="dialog-copy">“{titleOf(conversation)}” sẽ bị xoá vĩnh viễn. Bạn không thể hoàn tác thao tác này.</p><div className="dialog-actions"><button className="secondary-button" onClick={onClose}>Huỷ</button><button className="danger-button" onClick={onDelete}>Xoá</button></div></Modal>; }

function ArchivedDialog({ conversations, onClose, onUnarchive, onDelete }: { conversations: ConversationResponse[]; onClose: () => void; onUnarchive: (id: string) => void; onDelete: (item: ConversationResponse) => void }) { return <Modal title="Cuộc trò chuyện đã lưu trữ" onClose={onClose}><div className="archived-list">{!conversations.length && <p className="empty-dialog-copy">Chưa có cuộc trò chuyện nào được lưu trữ.</p>}{conversations.map((item) => <div className="archived-row" key={item.id}><span>{titleOf(item)}</span><div><button onClick={() => onUnarchive(item.id)}>Bỏ lưu trữ</button><button className="danger-text" onClick={() => onDelete(item)}>Xoá</button></div></div>)}</div></Modal>; }

function SettingsDialog({ user, onClose, onUserUpdated, onLogoutAll }: { user: UserResponse; onClose: () => void; onUserUpdated: (user: UserResponse) => void; onLogoutAll: () => Promise<void> }) {
  const [tab, setTab] = useState<"appearance" | "account">("appearance");
  const [name, setName] = useState(user.display_name || "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [passwordSaving, setPasswordSaving] = useState(false);
  const [passwordError, setPasswordError] = useState("");
  const [passwordSuccess, setPasswordSuccess] = useState("");
  const { appearance, setAppearance } = useAppearance();

  async function saveProfile(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      const updated = await api.updateMe(name.trim() || null);
      onUserUpdated(updated);
      setName(updated.display_name || "");
    } catch (cause) {
      setError(cause instanceof ApiError && cause.status !== 422 ? cause.message : "Không thể cập nhật thông tin tài khoản.");
    } finally {
      setSaving(false);
    }
  }

  async function createPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (passwordSaving) return;
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const password = String(form.get("password") || "");
    const confirmation = String(form.get("confirm_password") || "");
    setPasswordError("");
    setPasswordSuccess("");
    if (password !== confirmation) {
      setPasswordError("Mật khẩu xác nhận không khớp.");
      return;
    }
    setPasswordSaving(true);
    try {
      await api.createLocalPassword(password, confirmation);
      formElement.reset();
      setPasswordSuccess("Đã tạo mật khẩu. Bạn có thể dùng email và mật khẩu này để đăng nhập.");
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) {
        setPasswordError("Tài khoản đã có mật khẩu đăng nhập. Mật khẩu hiện tại không bị thay đổi.");
      } else if (cause instanceof ApiError && cause.status === 422) {
        setPasswordError("Mật khẩu phải có từ 8 đến 128 ký tự và hai ô phải trùng khớp.");
      } else {
        setPasswordError("Không thể tạo mật khẩu lúc này. Vui lòng thử lại.");
      }
    } finally {
      setPasswordSaving(false);
    }
  }

  return (
    <Modal title="Cài đặt" onClose={onClose} className="settings-modal">
      <div className="settings-layout">
        <nav className="settings-tabs" aria-label="Các mục cài đặt">
          <button className={tab === "appearance" ? "is-active" : ""} onClick={() => setTab("appearance")}>Giao diện</button>
          <button className={tab === "account" ? "is-active" : ""} onClick={() => setTab("account")}>Tài khoản</button>
        </nav>
        <div className="settings-content">
          {tab === "appearance" ? (
            <section>
              <h3>Giao diện</h3>
              <p>Chọn màu nền bạn muốn sử dụng trong ứng dụng.</p>
              <div className="appearance-options">
                {appearanceOptions.map((option) => (
                  <button key={option.value} className={appearance === option.value ? "is-selected" : ""} onClick={() => setAppearance(option.value)}>
                    <span className="appearance-swatch" style={{ background: option.swatch }} />
                    <span>{option.label}</span>
                    {appearance === option.value && <CheckIcon />}
                  </button>
                ))}
              </div>
            </section>
          ) : (
            <section>
              <h3>Tài khoản</h3>
              <div className="account-summary">
                <span className="avatar account-avatar">{(user.display_name || user.email).slice(0, 1).toUpperCase()}</span>
                <div><strong>{user.display_name || "Chưa đặt tên"}</strong><span>{user.email}</span></div>
              </div>
              <form className="profile-form" onSubmit={saveProfile}>
                <label><span>Tên hiển thị</span><input value={name} maxLength={120} onChange={(event) => setName(event.target.value)} /></label>
                {error && <div className="form-error" role="alert">{error}</div>}
                <button className="primary-button" disabled={saving}>{saving ? "Đang lưu..." : "Lưu thay đổi"}</button>
              </form>
              <form className="local-password-form" onSubmit={createPassword}>
                <div><strong>Tạo mật khẩu đăng nhập</strong><span>Dành cho tài khoản được tạo bằng Google. Thao tác này không thay thế mật khẩu đã có.</span></div>
                <label><span>Mật khẩu mới</span><input name="password" type="password" minLength={8} maxLength={128} autoComplete="new-password" required disabled={passwordSaving} /></label>
                <label><span>Xác nhận mật khẩu</span><input name="confirm_password" type="password" minLength={8} maxLength={128} autoComplete="new-password" required disabled={passwordSaving} /></label>
                {passwordError && <div className="form-error" role="alert">{passwordError}</div>}
                {passwordSuccess && <div className="form-success" role="status">{passwordSuccess}</div>}
                <button className="secondary-button" disabled={passwordSaving}>{passwordSaving ? "Đang tạo..." : "Tạo mật khẩu"}</button>
              </form>
              <div className="account-actions">
                <div><strong>Đăng xuất khỏi mọi thiết bị</strong><span>Thu hồi tất cả phiên đăng nhập đang hoạt động của tài khoản này.</span></div>
                <button className="secondary-button" onClick={() => void onLogoutAll()}>Đăng xuất tất cả</button>
              </div>
            </section>
          )}
        </div>
      </div>
    </Modal>
  );
}
