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
import { AccountSecurity } from "../components/AccountSecurity";
import { Button, Segmented } from "antd";
import { useLocale } from "../locale/LocaleProvider";
import { localizeNotification } from "../locale/notifications";
import { ThumbsDownIcon, ThumbsUpIcon } from "lucide-react";
import {
  ArchiveIcon, ChatIcon, CheckIcon, EditIcon, ExternalIcon, LogoutIcon, MenuIcon,
  MoreIcon, PlusIcon, SendIcon, SettingsIcon, TrashIcon, UsersIcon, WarningIcon,
} from "../components/Icons";

type Translate = (vi: string, en: string) => string;

function progressLabel(stage: AgentProgressStage, t: Translate) {
  return ({ planning: t("Đang phân tích yêu cầu", "Analyzing your request"), retrieving: t("Đang tìm thông tin du lịch", "Finding travel information"), validating: t("Đang kiểm tra nguồn", "Checking sources"), reasoning: t("Đang tổng hợp thông tin", "Putting the answer together"), generating: t("Đang soạn câu trả lời", "Writing the answer") } as Record<AgentProgressStage, string>)[stage];
}

function toolLabel(tool: string, t: Translate) {
  return ({ weather: t("Đang kiểm tra thời tiết", "Checking the weather"), search_travel_knowledge: t("Đang tra cứu thông tin du lịch", "Searching travel knowledge"), web_search: t("Đang tìm thông tin mới nhất", "Finding current information"), routing: t("Đang tính đường đi", "Calculating the route"), map_location: t("Đang xác định địa điểm", "Locating the destination"), distance_matrix: t("Đang so sánh khoảng cách", "Comparing distances") } as Record<string, string>)[tool] || t("Đang thu thập thông tin du lịch", "Gathering travel information");
}

function titleOf(conversation: ConversationResponse, fallback = "Cuộc trò chuyện mới") {
  return conversation.title || fallback;
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
  const { t } = useLocale();
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
    loadConversations().catch((cause) => active && handleApiError(cause, t("Không thể tải danh sách cuộc trò chuyện.", "Could not load conversations.")))
      .finally(() => active && setListLoading(false));
    return () => { active = false; };
  }, [handleApiError, loadConversations, t]);

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
      } else handleApiError(cause, t("Không thể tải lịch sử trò chuyện.", "Could not load conversation history."));
    } finally {
      setHistoryLoading(false);
    }
  }, [handleApiError, navigate, t]);

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
          else handleApiError(cause, t("Không thể mở cuộc trò chuyện này.", "Could not open this conversation."));
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
      handleApiError(cause, t("Không thể tạo cuộc trò chuyện mới.", "Could not create a new conversation."));
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
      setProgress(progressLabel("planning", t));
      let streamError: string | null = null;

      await api.streamMessage(id, value, (event) => {
        if (event.event === "connected") return;
        if (event.event === "stage") setProgress(progressLabel(event.data.stage, t));
        if (event.event === "tool" && event.data.status === "started") setProgress(toolLabel(event.data.tool, t));
        if (event.event === "error") streamError = event.data.message || t("Trợ lý chưa thể hoàn tất yêu cầu này.", "The assistant could not complete this request.");
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
      handleApiError(cause, t("Kết nối bị gián đoạn. Lịch sử trò chuyện đã được cập nhật lại.", "The connection was interrupted. Conversation history has been refreshed."));
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
    } catch (cause) { handleApiError(cause, t("Không thể đổi tên cuộc trò chuyện.", "Could not rename the conversation.")); }
  }

  async function archiveConversation(id: string, isArchived = true) {
    try {
      const updated = await api.updateConversation(id, { is_archived: isArchived });
      setConversations((current) => current.map((item) => item.id === id ? updated : item));
      setActiveMenu(null);
      if (conversationId === id && isArchived) navigate("/");
    } catch (cause) { handleApiError(cause, t("Không thể cập nhật cuộc trò chuyện.", "Could not update the conversation.")); }
  }

  async function deleteConversation(id: string) {
    try {
      await api.deleteConversation(id);
      setConversations((current) => current.filter((item) => item.id !== id));
      setDeleteTarget(null);
      if (conversationId === id) { setMessages([]); navigate("/"); }
    } catch (cause) { handleApiError(cause, t("Không thể xoá cuộc trò chuyện.", "Could not delete the conversation.")); }
  }

  async function openArchived() {
    setUserMenuOpen(false);
    try { await loadConversations(true); setArchivedOpen(true); }
    catch (cause) { handleApiError(cause, t("Không thể tải các cuộc trò chuyện đã lưu trữ.", "Could not load archived conversations.")); }
  }

  const displayName = user?.display_name || user?.email || t("Tài khoản", "Account");
  const initial = displayName.slice(0, 1).toUpperCase();

  return (
    <div className={`app-shell ${desktopCollapsed ? "sidebar-collapsed" : ""}`}>
      <aside className={`sidebar ${mobileSidebarOpen ? "is-open" : ""}`} aria-label={t("Lịch sử trò chuyện", "Conversation history")}>
        <div className="sidebar-head">
          <div className="sidebar-title-row">
            <Link className="brand" to="/"><span className="brand-full">Vietnam Travel Advisor</span><span className="brand-short">VTA</span></Link>
            <button className="sidebar-toggle-button" onClick={() => { if (window.matchMedia("(max-width: 760px)").matches) setMobileSidebarOpen(false); else setDesktopCollapsed((value) => !value); }} aria-label={t("Thu gọn hoặc mở rộng thanh bên", "Collapse or expand sidebar")}><MenuIcon /></button>
          </div>
          <button className="new-chat-button" onClick={newChat} disabled={sending}><PlusIcon /><span>{t("Cuộc trò chuyện mới", "New conversation")}</span></button>
        </div>
        <nav className="conversation-nav" aria-label={t("Danh sách cuộc trò chuyện", "Conversation list")}>
          {listLoading && <div className="history-skeleton"><span /><span /><span /></div>}
          {!listLoading && !visible.length && <p className="empty-dialog-copy">{t("Chưa có cuộc trò chuyện nào.", "No conversations yet.")}</p>}
          <ConversationGroup title={t("Hôm nay", "Today")} items={groups.today} activeId={conversationId} activeMenu={activeMenu} setActiveMenu={setActiveMenu} setRenameTarget={setRenameTarget} setDeleteTarget={setDeleteTarget} archiveConversation={archiveConversation} />
          <ConversationGroup title={t("Trước đó", "Earlier")} items={groups.previous} activeId={conversationId} activeMenu={activeMenu} setActiveMenu={setActiveMenu} setRenameTarget={setRenameTarget} setDeleteTarget={setDeleteTarget} archiveConversation={archiveConversation} />
        </nav>
        <div className="sidebar-user">
          <button className="user-row" onClick={() => setUserMenuOpen((value) => !value)} aria-expanded={userMenuOpen}><span className="avatar">{initial}</span><span>{displayName}</span><MoreIcon className="user-more" /></button>
          {userMenuOpen && <div className="user-menu">
            <button onClick={() => { setSettingsOpen(true); setUserMenuOpen(false); }}><SettingsIcon />{t("Cài đặt", "Settings")}</button>
            <button onClick={openArchived}><ArchiveIcon />{t("Cuộc trò chuyện đã lưu trữ", "Archived conversations")}</button>
            {user?.is_admin && <button onClick={() => navigate("/admin")}><UsersIcon />{t("Trang quản trị", "Admin console")}</button>}
            <button onClick={async () => { try { await logout(); } finally { navigate("/login"); } }}><LogoutIcon />{t("Đăng xuất", "Sign out")}</button>
          </div>}
        </div>
      </aside>
      {mobileSidebarOpen && <button className="mobile-backdrop" onClick={() => setMobileSidebarOpen(false)} aria-label={t("Đóng thanh bên", "Close sidebar")} />}
      <main className="chat-main">
        <header className="mobile-header"><button className="icon-button" onClick={() => setMobileSidebarOpen(true)} aria-label={t("Mở thanh bên", "Open sidebar")}><MenuIcon /></button><span>Vietnam Travel Advisor</span><span className="mobile-header-spacer" /></header>
        {!conversationId && pageError && <div className="inline-error chat-alert" role="alert">{localizeNotification(pageError)}</div>}
        {!conversationId ? <EmptyState onSuggestion={send} /> : activeConversation || historyLoading ? (
          <section className="conversation-view" ref={viewRef} aria-label={activeConversation ? titleOf(activeConversation, t("Cuộc trò chuyện mới", "New conversation")) : t("Cuộc trò chuyện", "Conversation")} onScroll={(event) => { const element = event.currentTarget; stayAtBottom.current = element.scrollHeight - element.scrollTop - element.clientHeight < 120; }}>
            <div className="message-list">
              {historyLoading && !messages.length && <div className="history-skeleton"><span /><span /><span /></div>}
              {messages.map((message) => <MessageView key={message.id} message={message} degraded={degradedIds.has(message.id)} onFeedback={message.role === "assistant" && conversationId ? async (feedback) => {
                const updated = await api.setMessageFeedback(conversationId, message.id, feedback);
                setMessages(current => current.map(item => item.id === updated.id ? updated : item));
              } : undefined} />)}
              {progress && <AgentProgress label={progress} />}
              {pageError && <div className="inline-error" role="alert">{localizeNotification(pageError)}</div>}
              {rateLimitSeconds !== null && <div className="inline-error" role="alert">{t(`Bạn thao tác quá nhanh. Vui lòng thử lại sau ${rateLimitSeconds} giây.`, `Too many requests. Try again in ${rateLimitSeconds} seconds.`)}</div>}
            </div>
          </section>
        ) : <section className="center-state"><h1>{t("Không tìm thấy cuộc trò chuyện", "Conversation not found")}</h1><p>{t("Cuộc trò chuyện này không còn khả dụng.", "This conversation is no longer available.")}</p><Button onClick={() => navigate("/")}>{t("Bắt đầu cuộc trò chuyện mới", "Start a new conversation")}</Button></section>}
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
  const { t } = useLocale();
  const buttonRef = useRef<HTMLButtonElement>(null);
  return <div className={`conversation-row ${active ? "is-active" : ""}`}>
    <Link to={`/c/${item.id}`}><ChatIcon /><span>{titleOf(item, t("Cuộc trò chuyện mới", "New conversation"))}</span></Link>
    <button ref={buttonRef} className="row-menu-button" onClick={() => setActiveMenu(menuOpen ? null : item.id)} aria-expanded={menuOpen} aria-haspopup="menu" aria-label={t(`Tuỳ chọn cho ${titleOf(item)}`, `Options for ${titleOf(item, "new conversation")}`)}><MoreIcon /></button>
    {menuOpen && <ConversationPopover anchorRef={buttonRef} onClose={() => setActiveMenu(null)}><button role="menuitem" onClick={() => { setRenameTarget(item); setActiveMenu(null); }}><EditIcon />{t("Đổi tên", "Rename")}</button><button role="menuitem" onClick={() => archiveConversation(item.id)}><ArchiveIcon />{t("Lưu trữ", "Archive")}</button><button role="menuitem" className="danger-text" onClick={() => { setDeleteTarget(item); setActiveMenu(null); }}><TrashIcon />{t("Xoá", "Delete")}</button></ConversationPopover>}
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
  const { t } = useLocale();
  const suggestions = [
    [t("Kiến thức du lịch", "Travel knowledge"), t("Đà Lạt có gì?", "What does Da Lat have to offer?")],
    [t("Gợi ý trải nghiệm", "Recommendations"), t("Ở Huế buổi tối nên đi đâu?", "Where should I go in Hue at night?")],
    [t("So sánh", "Compare"), t("Huế hay Hội An hợp đi 2 ngày hơn?", "Which is better for a two-day trip: Hue or Hoi An?")],
    [t("Lịch trình", "Itinerary"), t("Lên lịch trình Huế 3 ngày.", "Plan a three-day trip to Hue.")],
    [t("Thời tiết", "Weather"), t("Huế cuối tuần có mưa không?", "Will it rain in Hue this weekend?")],
    [t("Đường đi", "Routing"), t("Từ Đại Nội đến lăng Khải Định bao xa?", "How far is it from the Imperial City to Khai Dinh Tomb?")],
    [t("Thông tin mới", "Current info"), t("Huế hiện có sự kiện gì?", "What events are happening in Hue right now?")],
    [t("Trò chuyện", "General"), t("Tôi muốn đi du lịch nhưng chưa biết đi đâu.", "I want to travel but do not know where to go yet.")],
  ];
  return <section className="empty-state"><div className="empty-copy"><div className="empty-kicker">V</div><h1>{t("Bạn muốn khám phá đâu hôm nay?", "Where would you like to explore today?")}</h1><p>{t("Hỏi kiến thức du lịch, gợi ý điểm đến, so sánh lựa chọn, xem thời tiết, tính đường hoặc nhờ mình lên lịch trình.", "Ask about travel knowledge, recommendations, comparisons, weather, routing, or itinerary planning.")}</p></div><div className="suggestions" aria-label={t("Câu hỏi gợi ý", "Suggested questions")}>{suggestions.map(([label, question]) => <button key={question} onClick={() => onSuggestion(question)}><strong>{label}</strong><span>{question}</span></button>)}</div></section>;
}

export function MessageView({ message, degraded, onFeedback }: { message: MessageResponse; degraded: boolean; onFeedback?: (feedback: -1 | 1 | null) => Promise<void> }) {
  const { t } = useLocale();
  if (message.role === "user") return <article className="user-message"><div className="message-meta">{t("Bạn", "You")}</div><p>{message.content}</p></article>;
  return <article className="assistant-message"><div className="assistant-mark">AI</div><div className="assistant-bubble"><div className="message-meta assistant-label">Vietnam Travel Advisor</div><MarkdownLite content={message.content} />{message.citations?.length ? <CitationList citations={message.citations} /> : null}{(degraded || message.warnings?.length) ? <div className="warning-row"><WarningIcon /><div>{t("Một số thông tin chưa thể được kiểm chứng đầy đủ.", "Some information could not be fully verified.")}</div></div> : null}{onFeedback && <div className="message-feedback" aria-label={t("Đánh giá câu trả lời", "Rate answer")}><button type="button" className={message.feedback === 1 ? "is-active" : ""} aria-label={t("Câu trả lời hữu ích", "Helpful answer")} aria-pressed={message.feedback === 1} onClick={() => void onFeedback(message.feedback === 1 ? null : 1)}><ThumbsUpIcon /></button><button type="button" className={message.feedback === -1 ? "is-active" : ""} aria-label={t("Câu trả lời chưa hữu ích", "Unhelpful answer")} aria-pressed={message.feedback === -1} onClick={() => void onFeedback(message.feedback === -1 ? null : -1)}><ThumbsDownIcon /></button></div>}</div></article>;
}

function CitationList({ citations }: { citations: CitationResponse[] }) {
  const { t } = useLocale();
  return <section className="citations" aria-label={t("Nguồn", "Sources")}><h3>{t("Nguồn tham khảo", "Sources")}</h3><div className="citation-list">{citations.map((citation) => citation.url ? <a key={citation.citation_id} href={citation.url} target="_blank" rel="noreferrer"><span>[{citation.citation_id}]</span>{citation.title}<ExternalIcon /></a> : <div className="citation-static" key={citation.citation_id}><span>[{citation.citation_id}]</span>{citation.title}</div>)}</div></section>;
}

function AgentProgress({ label }: { label: string }) { return <div className="agent-progress" role="status" aria-live="polite"><span className="progress-dot" /><span>{label}...</span></div>; }

function Composer(props: { draft: string; setDraft: (value: string) => void; onSubmit: (event: FormEvent) => void; loading: boolean; blocked: boolean; textareaRef: RefObject<HTMLTextAreaElement | null> }) {
  const { language, t } = useLocale();
  useEffect(() => {
    const textarea = props.textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 144)}px`;
  }, [props.draft, props.textareaRef]);
  return <form className="composer-wrap" onSubmit={props.onSubmit}><div className="composer"><textarea ref={props.textareaRef} value={props.draft} onChange={(event) => props.setDraft(event.target.value.slice(0, 10000))} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} placeholder={t("Bạn muốn hỏi gì về chuyến đi?", "What would you like to know about your trip?")} rows={1} aria-label={t("Nội dung tin nhắn", "Message")} disabled={props.loading || props.blocked} /><button className="send-button" disabled={!props.draft.trim() || props.loading || props.blocked} aria-label={t("Gửi", "Send")}><SendIcon /></button></div><div className="character-count">{props.draft.length.toLocaleString(language === "vi" ? "vi-VN" : "en-US")}/10,000</div></form>;
}

function RenameDialog({ conversation, onClose, onSave }: { conversation: ConversationResponse; onClose: () => void; onSave: (value: string) => void }) {
  const { t } = useLocale();
  const [value, setValue] = useState(titleOf(conversation, t("Cuộc trò chuyện mới", "New conversation")));
  return <Modal title={t("Đổi tên cuộc trò chuyện", "Rename conversation")} onClose={onClose}><form className="dialog-form" onSubmit={(event) => { event.preventDefault(); onSave(value); }}><label><span>{t("Tên cuộc trò chuyện", "Conversation name")}</span><input value={value} maxLength={255} onChange={(event) => setValue(event.target.value)} autoFocus /></label><div className="dialog-actions"><Button onClick={onClose}>{t("Huỷ", "Cancel")}</Button><Button htmlType="submit" type="primary" disabled={!value.trim()}>{t("Lưu", "Save")}</Button></div></form></Modal>;
}

function DeleteDialog({ conversation, onClose, onDelete }: { conversation: ConversationResponse; onClose: () => void; onDelete: () => void }) { const { t } = useLocale(); return <Modal title={t("Xoá cuộc trò chuyện?", "Delete conversation?")} onClose={onClose}><p className="dialog-copy">{t(`“${titleOf(conversation)}” sẽ bị xoá vĩnh viễn. Bạn không thể hoàn tác thao tác này.`, `“${titleOf(conversation, "New conversation")}” will be permanently deleted. This cannot be undone.`)}</p><div className="dialog-actions"><Button onClick={onClose}>{t("Huỷ", "Cancel")}</Button><Button danger type="primary" onClick={onDelete}>{t("Xoá", "Delete")}</Button></div></Modal>; }

function ArchivedDialog({ conversations, onClose, onUnarchive, onDelete }: { conversations: ConversationResponse[]; onClose: () => void; onUnarchive: (id: string) => void; onDelete: (item: ConversationResponse) => void }) { const { t } = useLocale(); return <Modal title={t("Cuộc trò chuyện đã lưu trữ", "Archived conversations")} onClose={onClose}><div className="archived-list">{!conversations.length && <p className="empty-dialog-copy">{t("Chưa có cuộc trò chuyện nào được lưu trữ.", "No archived conversations.")}</p>}{conversations.map((item) => <div className="archived-row" key={item.id}><span>{titleOf(item, t("Cuộc trò chuyện mới", "New conversation"))}</span><div><button onClick={() => onUnarchive(item.id)}>{t("Bỏ lưu trữ", "Unarchive")}</button><button className="danger-text" onClick={() => onDelete(item)}>{t("Xoá", "Delete")}</button></div></div>)}</div></Modal>; }

function SettingsDialog({ user, onClose, onUserUpdated, onLogoutAll }: { user: UserResponse; onClose: () => void; onUserUpdated: (user: UserResponse) => void; onLogoutAll: () => Promise<void> }) {
  const [tab, setTab] = useState<"appearance" | "account">("appearance");
  const [name, setName] = useState(user.display_name || "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const { appearance, setAppearance, mode, setMode } = useAppearance();
  const { t } = useLocale();

  async function saveProfile(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      const updated = await api.updateMe(name.trim() || null);
      onUserUpdated(updated);
      setName(updated.display_name || "");
    } catch (cause) {
      setError(cause instanceof ApiError && cause.status !== 422 ? cause.message : t("Không thể cập nhật thông tin tài khoản.", "Could not update your account."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={t("Cài đặt", "Settings")} onClose={onClose} className="settings-modal">
      <div className="settings-layout">
        <nav className="settings-tabs" aria-label={t("Các mục cài đặt", "Settings sections")}>
          <button className={tab === "appearance" ? "is-active" : ""} onClick={() => setTab("appearance")}>{t("Giao diện", "Appearance")}</button>
          <button className={tab === "account" ? "is-active" : ""} onClick={() => setTab("account")}>{t("Tài khoản", "Account")}</button>
        </nav>
        <div className="settings-content">
          {tab === "appearance" ? (
            <section>
              <h3>{t("Giao diện", "Appearance")}</h3>
              <p>Chọn chủ đề và màu giao diện.</p>
              <div className="setting-control"><span>{t("Chủ đề", "Theme")}</span><Segmented value={mode} onChange={(value) => setMode(value as "light" | "dark" | "system")} options={[{ label: t("Sáng", "Light"), value: "light" }, { label: t("Tối", "Dark"), value: "dark" }, { label: t("Hệ thống", "System"), value: "system" }]} /></div>
              <div className="appearance-options">
                {appearanceOptions.map((option) => (
                  <button key={option.value} className={appearance === option.value ? "is-selected" : ""} onClick={() => setAppearance(option.value)}>
                    <span className="appearance-swatch" style={{ background: option.swatch }} />
                    <span>{option.value === "pink" ? t("Hồng san hô", "Coral") : option.value === "yellow" ? t("Vàng", "Yellow") : t("Xanh lá", "Green")}</span>
                    {appearance === option.value && <CheckIcon />}
                  </button>
                ))}
              </div>
            </section>
          ) : (
            <section>
              <h3>{t("Tài khoản", "Account")}</h3>
              <div className="account-summary">
                <span className="avatar account-avatar">{(user.display_name || user.email).slice(0, 1).toUpperCase()}</span>
                <div><strong>{user.display_name || t("Chưa đặt tên", "Unnamed")}</strong><span>{user.email}</span></div>
              </div>
              <form className="profile-form" onSubmit={saveProfile}>
                <label><span>{t("Tên hiển thị", "Display name")}</span><input value={name} maxLength={120} onChange={(event) => setName(event.target.value)} /></label>
                {error && <div className="form-error" role="alert">{localizeNotification(error)}</div>}
                <Button htmlType="submit" type="primary" loading={saving}>{t("Lưu thay đổi", "Save changes")}</Button>
              </form>
              <AccountSecurity email={user.email} />
              <div className="account-actions">
                <div><strong>{t("Đăng xuất khỏi mọi thiết bị", "Sign out everywhere")}</strong><span>{t("Thu hồi tất cả phiên đăng nhập đang hoạt động của tài khoản này.", "Revoke every active session for this account.")}</span></div>
                <Button onClick={() => void onLogoutAll()}>{t("Đăng xuất tất cả", "Sign out all")}</Button>
              </div>
            </section>
          )}
        </div>
      </div>
    </Modal>
  );
}
