import { FormEvent, useMemo, useState } from "react";
import {
  ChatIcon, CopyIcon, DislikeIcon, EditIcon, GearIcon, LikeIcon,
  MoreIcon, PlusIcon, RefreshIcon, SearchIcon, SendIcon, TrashIcon,
} from "./components/Icons";

type Conversation = { id: number; title: string; disabled?: boolean };
type ChatMessage = { id: number; role: "user" | "assistant"; body: string };

const initialConversations: Conversation[] = [
  { id: 1, title: "Create Html Game Environment..." },
  { id: 2, title: "Apply To Leave For Emergency" },
  { id: 3, title: "What Is UI UX Design?" },
  { id: 4, title: "Create POS System" },
  { id: 5, title: "What Is UX Audit?" },
  { id: 6, title: "Create Chatbot GPT..." },
  { id: 7, title: "How Chat GPT Work?" },
  { id: 8, title: "Crypto Lending App Name" },
  { id: 9, title: "Operator Grammar Types" },
  { id: 10, title: "Min States For Binary DFA", disabled: true },
];

const firstAnswer = `Sure, I can help you get started with creating a chatbot using GPT in Python. Here are the basic steps you'll need to follow:`;

export default function App() {
  const [activeId, setActiveId] = useState(6);
  const [conversations, setConversations] = useState(initialConversations);
  const [draft, setDraft] = useState("");
  const [extraMessages, setExtraMessages] = useState<ChatMessage[]>([]);

  const selected = useMemo(() => conversations.find((item) => item.id === activeId), [activeId, conversations]);

  function createNewChat() {
    const next = Math.max(0, ...conversations.map((item) => item.id)) + 1;
    setConversations((current) => [...current, { id: next, title: "New conversation" }]);
    setActiveId(next);
    setExtraMessages([]);
  }

  function clearAll() {
    setConversations([]);
    setExtraMessages([]);
  }

  function send(event: FormEvent) {
    event.preventDefault();
    const value = draft.trim();
    if (!value) return;
    setExtraMessages((current) => [...current, { id: Date.now(), role: "user", body: value }]);
    setDraft("");
  }

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="Conversation sidebar">
        <header className="sidebar-header">
          <div className="brand">CHAT A.I+</div>
          <div className="new-chat-row">
            <button className="new-chat" onClick={createNewChat}><PlusIcon />New chat</button>
            <button className="search-button" aria-label="Search"><SearchIcon /></button>
          </div>
        </header>

        <div className="conversation-label-row">
          <span>Your conversations</span>
          <button className="clear-button" onClick={clearAll}>Clear All</button>
        </div>

        <nav className="conversation-list">
          {conversations.slice(0, 7).map((item) => (
            <button
              key={item.id}
              className={`conversation-item ${activeId === item.id ? "is-active" : ""}`}
              onClick={() => !item.disabled && setActiveId(item.id)}
              disabled={item.disabled}
            >
              <ChatIcon />
              <span>{item.title}</span>
              {activeId === item.id && (
                <span className="row-actions" aria-hidden="true"><TrashIcon /><EditIcon /></span>
              )}
            </button>
          ))}
          {conversations.length > 7 && <div className="period-label">Last 7 Days</div>}
          {conversations.slice(7).map((item) => (
            <button
              key={item.id}
              className={`conversation-item ${activeId === item.id ? "is-active" : ""}`}
              onClick={() => !item.disabled && setActiveId(item.id)}
              disabled={item.disabled}
            >
              <ChatIcon />
              <span>{item.title}</span>
            </button>
          ))}
        </nav>

        <footer className="sidebar-footer">
          <button className="footer-row"><span className="footer-icon"><GearIcon /></span><span>Settings</span></button>
          <button className="footer-row"><span className="avatar avatar-small">AN</span><span>Andrew Neilson</span></button>
        </footer>
      </aside>

      <main className="chat-main">
        <div className="conversation-canvas">
          <section className="message-block first-message">
            <div className="message-topline">
              <div className="user-line"><span className="avatar avatar-xs">AN</span><span>Create a chatbot gpt using python language what will be step for that</span></div>
              <button className="edit-message" aria-label="Edit message"><EditIcon /></button>
            </div>
            <div className="assistant-name">CHAT A.I+ <span>◉</span></div>
            <p className="lead"><strong>{firstAnswer}</strong></p>
            <ol className="answer-list">
              <li><strong>Install the required libraries:</strong> You'll need to install the transformers library from Hugging Face to use GPT. You can install it using pip.</li>
              <li><strong>Load the pre-trained model:</strong> GPT comes in several sizes and versions, so you'll need to choose the one that fits your needs. You can load a pre-trained GPT model. This loads the 1.3B parameter version of GPT-Neo, which is a powerful and relatively recent model.</li>
              <li><strong>Create a chatbot loop:</strong> You'll need to create a loop that takes user input, generates a response using the GPT model, and outputs it to the user. Here's an example loop that uses the input() function to get user input and the gpt() function to generate a response, This loop will keep running until the user exits the program or the loop is interrupted.</li>
              <li><strong>Add some personality to the chatbot:</strong> While GPT can generate text, it doesn't have any inherent personality or style. You can make your chatbot more interesting by adding custom prompts or responses that reflect your desired personality. You can then modify the chatbot loop to use these prompts and responses when appropriate. This will make the chatbot seem more human-like and engaging.</li>
            </ol>
            <p className="closing"><strong>These are just the basic steps to get started with a GPT chatbot in Python. Depending on your requirements, you may need to add more features or complexity to the chatbot. Good luck!</strong></p>
            <div className="response-actions">
              <div className="action-group"><button><LikeIcon /></button><button><DislikeIcon /></button><button><CopyIcon /></button></div>
              <button className="more-button"><MoreIcon /></button>
              <button className="regenerate"><RefreshIcon />Regenerate</button>
            </div>
          </section>

          <div className="divider" />

          <section className="message-block second-message">
            <div className="message-topline">
              <div className="user-line"><span className="avatar avatar-xs">AN</span><span>What is use of that chatbot ?</span></div>
              <button className="edit-message" aria-label="Edit message"><EditIcon /></button>
            </div>
            <div className="assistant-name">CHAT A.I+ <span>◉</span></div>
            <p className="lead"><strong>Chatbots can be used for a wide range of purposes, including:</strong></p>
            <p className="muted-answer">Customer service chatbots can handle frequently asked questions, provide basic support, and help customers navigate products and services. They can also guide users toward relevant resources.</p>
          </section>

          {extraMessages.map((message) => (
            <section className="message-block extra-message" key={message.id}>
              <div className="message-topline"><div className="user-line"><span className="avatar avatar-xs">AN</span><span>{message.body}</span></div></div>
            </section>
          ))}
        </div>

        <form className="composer" onSubmit={send}>
          <span className="brain" aria-hidden="true">🧠</span>
          <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="What's in your mind?..." aria-label="Message" />
          <button type="submit" className="send" aria-label="Send"><SendIcon /></button>
        </form>

        <div className="upgrade-tab" aria-hidden="true"><span>Upgrade to Pro</span><span className="sparkle">✦</span></div>
      </main>
    </div>
  );
}
