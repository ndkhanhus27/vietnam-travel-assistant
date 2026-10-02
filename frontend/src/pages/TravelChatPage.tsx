import { FormEvent, useCallback, useEffect, useMemo, useRef, useState, type RefObject } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { reconcileCompletedMessages } from "../api/chatState";
import type { AgentProgressStage, CitationResponse, ConversationResponse, MessageResponse, UserResponse } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { MarkdownLite } from "../components/MarkdownLite";
import { Modal } from "../components/Modal";
import {
  ArchiveIcon, ChatIcon, CloseIcon, EditIcon, ExternalIcon, LogoutIcon, MenuIcon,
  MoreIcon, PlusIcon, SendIcon, TrashIcon, UserIcon, WarningIcon,
} from "../components/Icons";

const suggestions = [
  "Plan a three-day nature-focused trip to Da Lat",
  "Suggest destinations in Vietnam for a couple",
  "Compare Hue and Hoi An",
  "Will it rain in Da Nang tomorrow?",
];

const progressLabels: Record<AgentProgressStage, string> = {
  planning: "Analyzing your request",
  retrieving: "Searching travel information",
  validating: "Checking evidence",
  reasoning: "Organizing information",
  generating: "Preparing response",
};

const toolLabels: Record<string, string> = {
  weather: "Checking weather",
  search_travel_knowledge: "Searching travel information",
  web_search: "Checking current information",
  routing: "Calculating route",
  map_location: "Locating place",
  budget_calculator: "Calculating budget",
  distance_matrix: "Comparing travel distances",
};

function titleOf(conversation: ConversationResponse) {
  return conversation.title || "New conversation";
}

function groupConversations(conversations: ConversationResponse[]) {
  return { today: conversations.slice(0, 2), previous: conversations.slice(2) };
}

function sortMessages(messages: MessageResponse[]) {
  return [...messages].sort((a, b) => a.sequence_no - b.sequence_no);
}

export function TravelChatPage() {
  const { conversationId } = useParams();
  const navigate = useNavigate();
  const { user, logout } = useAuth();
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
  const [accountOpen, setAccountOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [rateLimitSeconds, setRateLimitSeconds] = useState<number | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const viewRef = useRef<HTMLElement>(null);
  const stayAtBottom = useRef(true);

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
      else setPageError(cause.message || fallback);
    } else setPageError(fallback);
  }, []);

  useEffect(() => {
    let active = true;
    setListLoading(true);
    loadConversations().catch((cause) => active && handleApiError(cause, "Could not load conversations."))
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
      } else handleApiError(cause, "Could not load conversation history.");
    } finally {
      setHistoryLoading(false);
    }
  }, [handleApiError, navigate]);

  useEffect(() => {
    setActiveMenu(null);
    setUserMenuOpen(false);
    setPageError("");
    setMessages([]);
    if (!conversationId) return;
    void (async () => {
      if (!conversations.some((item) => item.id === conversationId)) {
        try {
          const conversation = await api.getConversation(conversationId);
          setConversations((current) => [conversation, ...current.filter((item) => item.id !== conversation.id)]);
        } catch (cause) {
          if (cause instanceof ApiError && cause.status === 404) navigate("/", { replace: true });
          else handleApiError(cause, "Could not open this conversation.");
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
      handleApiError(cause, "Could not create a conversation.");
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
        navigate(`/c/${id}`);
      }
      const optimisticId = `optimistic-${crypto.randomUUID()}`;
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
        if (event.event === "stage") setProgress(event.data.message || progressLabels[event.data.stage]);
        if (event.event === "tool" && event.data.status === "started") setProgress(toolLabels[event.data.tool] || "Gathering travel information");
        if (event.event === "error") streamError = event.data.message || "The assistant could not complete this request.";
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
      handleApiError(cause, "The connection was interrupted. History has been refreshed.");
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
    } catch (cause) { handleApiError(cause, "Could not rename the conversation."); }
  }

  async function archiveConversation(id: string, isArchived = true) {
    try {
      const updated = await api.updateConversation(id, { is_archived: isArchived });
      setConversations((current) => current.map((item) => item.id === id ? updated : item));
      setActiveMenu(null);
      if (conversationId === id && isArchived) navigate("/");
    } catch (cause) { handleApiError(cause, "Could not update the conversation."); }
  }

  async function deleteConversation(id: string) {
    try {
      await api.deleteConversation(id);
      setConversations((current) => current.filter((item) => item.id !== id));
      setDeleteTarget(null);
      if (conversationId === id) { setMessages([]); navigate("/"); }
    } catch (cause) { handleApiError(cause, "Could not delete the conversation."); }
  }

  async function openArchived() {
    setUserMenuOpen(false);
    try { await loadConversations(true); setArchivedOpen(true); }
    catch (cause) { handleApiError(cause, "Could not load archived conversations."); }
  }

  const displayName = user?.display_name || user?.email || "Account";
  const initial = displayName.slice(0, 1).toUpperCase();

  return (
    <div className={`app-shell ${desktopCollapsed ? "sidebar-collapsed" : ""}`}>
      <aside className={`sidebar ${mobileSidebarOpen ? "is-open" : ""}`} aria-label="Conversation sidebar">
        <div className="sidebar-head">
          <div className="sidebar-title-row">
            <Link className="brand" to="/"><span className="brand-full">Vietnam Travel Advisor</span><span className="brand-short">VTA</span></Link>
            <button className="collapse-button" onClick={() => setDesktopCollapsed((value) => !value)} aria-label={desktopCollapsed ? "Expand sidebar" : "Collapse sidebar"}><MenuIcon /></button>
            <button className="mobile-sidebar-close" onClick={() => setMobileSidebarOpen(false)} aria-label="Close sidebar"><CloseIcon /></button>
          </div>
          <button className="new-chat-button" onClick={newChat} disabled={sending}><PlusIcon /><span>New chat</span></button>
        </div>
        <nav className="conversation-nav" aria-label="Conversation history">
          {listLoading && <div className="history-skeleton"><span /><span /><span /></div>}
          {!listLoading && !visible.length && <p className="empty-dialog-copy">No conversations yet.</p>}
          <ConversationGroup title="Today" items={groups.today} activeId={conversationId} activeMenu={activeMenu} setActiveMenu={setActiveMenu} setRenameTarget={setRenameTarget} setDeleteTarget={setDeleteTarget} archiveConversation={archiveConversation} />
          <ConversationGroup title="Previous" items={groups.previous} activeId={conversationId} activeMenu={activeMenu} setActiveMenu={setActiveMenu} setRenameTarget={setRenameTarget} setDeleteTarget={setDeleteTarget} archiveConversation={archiveConversation} />
        </nav>
        <div className="sidebar-user">
          <button className="user-row" onClick={() => setUserMenuOpen((value) => !value)} aria-expanded={userMenuOpen}><span className="avatar">{initial}</span><span>{displayName}</span><MoreIcon className="user-more" /></button>
          {userMenuOpen && <div className="user-menu">
            <button onClick={() => { setAccountOpen(true); setUserMenuOpen(false); }}><UserIcon />Account</button>
            <button onClick={openArchived}><ArchiveIcon />Archived chats</button>
            <button onClick={async () => { try { await logout(); } finally { navigate("/login"); } }}><LogoutIcon />Log out</button>
          </div>}
        </div>
      </aside>
      {mobileSidebarOpen && <button className="mobile-backdrop" onClick={() => setMobileSidebarOpen(false)} aria-label="Close sidebar" />}
      <main className="chat-main">
        <header className="mobile-header"><button className="icon-button" onClick={() => setMobileSidebarOpen(true)} aria-label="Open sidebar"><MenuIcon /></button><span>Vietnam Travel Advisor</span><span className="mobile-header-spacer" /></header>
        {!conversationId ? <EmptyState onSuggestion={send} /> : activeConversation || historyLoading ? (
          <section className="conversation-view" ref={viewRef} aria-label={activeConversation ? titleOf(activeConversation) : "Conversation"} onScroll={(event) => { const element = event.currentTarget; stayAtBottom.current = element.scrollHeight - element.scrollTop - element.clientHeight < 120; }}>
            <div className="message-list">
              {historyLoading && !messages.length && <div className="history-skeleton"><span /><span /><span /></div>}
              {messages.map((message) => <MessageView key={message.id} message={message} degraded={degradedIds.has(message.id)} />)}
              {progress && <AgentProgress label={progress} />}
              {pageError && <div className="inline-error" role="alert">{pageError}</div>}
              {rateLimitSeconds !== null && <div className="inline-error" role="alert">Too many requests. Try again in {rateLimitSeconds} seconds.</div>}
            </div>
          </section>
        ) : <section className="center-state"><h1>Conversation not found</h1><p>This conversation is no longer available.</p><button className="secondary-button" onClick={() => navigate("/")}>Return to New Chat</button></section>}
        <Composer draft={draft} setDraft={setDraft} onSubmit={(event) => { event.preventDefault(); void send(); }} loading={sending} blocked={rateLimitSeconds !== null} textareaRef={textareaRef} />
      </main>
      {renameTarget && <RenameDialog conversation={renameTarget} onClose={() => setRenameTarget(null)} onSave={renameConversation} />}
      {deleteTarget && <DeleteDialog conversation={deleteTarget} onClose={() => setDeleteTarget(null)} onDelete={() => deleteConversation(deleteTarget.id)} />}
      {archivedOpen && <ArchivedDialog conversations={archived} onClose={() => { setArchivedOpen(false); void loadConversations(); }} onUnarchive={(id) => archiveConversation(id, false)} onDelete={(item) => { setArchivedOpen(false); setDeleteTarget(item); }} />}
      {accountOpen && user && <AccountDialog user={user} onClose={() => setAccountOpen(false)} />}
    </div>
  );
}

function ConversationGroup(props: { title: string; items: ConversationResponse[]; activeId?: string; activeMenu: string | null; setActiveMenu: (id: string | null) => void; setRenameTarget: (item: ConversationResponse) => void; setDeleteTarget: (item: ConversationResponse) => void; archiveConversation: (id: string) => void }) {
  if (!props.items.length) return null;
  return <section className="conversation-group"><div className="group-label">{props.title}</div>{props.items.map((item) => (
    <div className={`conversation-row ${props.activeId === item.id ? "is-active" : ""}`} key={item.id}>
      <Link to={`/c/${item.id}`}><ChatIcon /><span>{titleOf(item)}</span></Link>
      <button className="row-menu-button" onClick={() => props.setActiveMenu(props.activeMenu === item.id ? null : item.id)} aria-label={`Menu ${titleOf(item)}`}><MoreIcon /></button>
      {props.activeMenu === item.id && <div className="row-menu"><button onClick={() => { props.setRenameTarget(item); props.setActiveMenu(null); }}><EditIcon />Rename</button><button onClick={() => props.archiveConversation(item.id)}><ArchiveIcon />Archive</button><button className="danger-text" onClick={() => { props.setDeleteTarget(item); props.setActiveMenu(null); }}><TrashIcon />Delete</button></div>}
    </div>
  ))}</section>;
}

function EmptyState({ onSuggestion }: { onSuggestion: (text: string) => void }) {
  return <section className="empty-state"><div className="empty-copy"><div className="empty-kicker">Vietnam Travel Advisor</div><h1>Where would you like to explore in Vietnam?</h1><p>Ask about destinations, itineraries, weather, routes, budgets, or compare travel options.</p></div><div className="suggestions" aria-label="Prompt suggestions">{suggestions.map((item) => <button key={item} onClick={() => onSuggestion(item)}>{item}</button>)}</div></section>;
}

export function MessageView({ message, degraded }: { message: MessageResponse; degraded: boolean }) {
  if (message.role === "user") return <article className="user-message"><div className="message-meta">You</div><p>{message.content}</p></article>;
  return <article className="assistant-message"><div className="message-meta assistant-label">Vietnam Travel Advisor</div><MarkdownLite content={message.content} />{message.citations?.length ? <CitationList citations={message.citations} /> : null}{(degraded || message.warnings?.length) ? <div className="warning-row"><WarningIcon /><div>{message.warnings?.[0] || "Some information could not be fully verified."}</div></div> : null}</article>;
}

function CitationList({ citations }: { citations: CitationResponse[] }) {
  return <section className="citations" aria-label="Sources"><h3>Sources</h3><div className="citation-list">{citations.map((citation) => citation.url ? <a key={citation.citation_id} href={citation.url} target="_blank" rel="noreferrer"><span>[{citation.citation_id}]</span>{citation.title}<ExternalIcon /></a> : <div className="citation-static" key={citation.citation_id}><span>[{citation.citation_id}]</span>{citation.title}</div>)}</div></section>;
}

function AgentProgress({ label }: { label: string }) { return <div className="agent-progress" role="status" aria-live="polite"><span className="progress-dot" /><span>{label}...</span></div>; }

function Composer(props: { draft: string; setDraft: (value: string) => void; onSubmit: (event: FormEvent) => void; loading: boolean; blocked: boolean; textareaRef: RefObject<HTMLTextAreaElement | null> }) {
  return <form className="composer-wrap" onSubmit={props.onSubmit}><div className="composer"><textarea ref={props.textareaRef} value={props.draft} onChange={(event) => props.setDraft(event.target.value.slice(0, 10000))} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} placeholder="Ask about your Vietnam trip..." rows={1} aria-label="Message" disabled={props.loading || props.blocked} /><button className="send-button" disabled={!props.draft.trim() || props.loading || props.blocked} aria-label="Send"><SendIcon /></button></div><div className="character-count">{props.draft.length.toLocaleString()}/10,000</div></form>;
}

function RenameDialog({ conversation, onClose, onSave }: { conversation: ConversationResponse; onClose: () => void; onSave: (value: string) => void }) {
  const [value, setValue] = useState(titleOf(conversation));
  return <Modal title="Rename conversation" onClose={onClose}><form className="dialog-form" onSubmit={(event) => { event.preventDefault(); onSave(value); }}><label><span>Conversation name</span><input value={value} maxLength={255} onChange={(event) => setValue(event.target.value)} autoFocus /></label><div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose}>Cancel</button><button className="primary-button" disabled={!value.trim()}>Save</button></div></form></Modal>;
}

function DeleteDialog({ conversation, onClose, onDelete }: { conversation: ConversationResponse; onClose: () => void; onDelete: () => void }) { return <Modal title="Delete conversation?" onClose={onClose}><p className="dialog-copy">"{titleOf(conversation)}" will be deleted. This cannot be undone.</p><div className="dialog-actions"><button className="secondary-button" onClick={onClose}>Cancel</button><button className="danger-button" onClick={onDelete}>Delete</button></div></Modal>; }

function ArchivedDialog({ conversations, onClose, onUnarchive, onDelete }: { conversations: ConversationResponse[]; onClose: () => void; onUnarchive: (id: string) => void; onDelete: (item: ConversationResponse) => void }) { return <Modal title="Archived chats" onClose={onClose}><div className="archived-list">{!conversations.length && <p className="empty-dialog-copy">No archived conversations.</p>}{conversations.map((item) => <div className="archived-row" key={item.id}><span>{titleOf(item)}</span><div><button onClick={() => onUnarchive(item.id)}>Unarchive</button><button className="danger-text" onClick={() => onDelete(item)}>Delete</button></div></div>)}</div></Modal>; }

function AccountDialog({ user, onClose }: { user: UserResponse; onClose: () => void }) {
  const displayName = user.display_name || user.email;
  return <Modal title="Account" onClose={onClose}><div className="account-view"><span className="avatar account-avatar">{displayName.slice(0, 1).toUpperCase()}</span><dl><div><dt>Display name</dt><dd>{user.display_name || "Not set"}</dd></div><div><dt>Email</dt><dd>{user.email}</dd></div><div><dt>Verified</dt><dd>{user.is_verified ? "Yes" : "No"}</dd></div></dl><p>Account information is read-only.</p></div></Modal>;
}
