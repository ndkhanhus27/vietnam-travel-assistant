import type { ReactNode } from "react";

type Props = { content: string };

function safeUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.toString() : null;
  } catch {
    return null;
  }
}

function inline(text: string): ReactNode[] {
  const pattern = /(!?\[[^\]]+\]\([^)]+\)|\*\*[^*]+\*\*|`[^`]+`)/g;
  return text.split(pattern).filter(Boolean).map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={index}>{part.slice(1, -1)}</code>;
    }
    const image = part.match(/^!\[([^\]]+)\]\(([^)]+)\)$/);
    if (image) {
      const url = safeUrl(image[2]);
      return url ? <img key={index} src={url} alt={image[1]} loading="lazy" /> : image[1];
    }
    const link = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
    if (link) {
      const url = safeUrl(link[2]);
      return url ? <a key={index} href={url} target="_blank" rel="noreferrer">{link[1]}</a> : link[1];
    }
    return part;
  });
}

export function MarkdownLite({ content }: Props) {
  const lines = content.split("\n");
  const output: ReactNode[] = [];
  let list: string[] = [];
  let code: string[] = [];
  let codeLanguage = "";
  let inCode = false;

  function flushList() {
    if (!list.length) return;
    output.push(
      <ul key={`list-${output.length}`} className="answer-list">
        {list.map((item, i) => <li key={i}>{inline(item)}</li>)}
      </ul>,
    );
    list = [];
  }

  function flushCode() {
    if (code.length) {
      output.push(
        <pre key={`code-${output.length}`}><code className={codeLanguage ? `language-${codeLanguage}` : undefined}>{code.join("\n")}</code></pre>,
      );
    }
    code = [];
    codeLanguage = "";
    inCode = false;
  }

  lines.forEach((line, index) => {
    if (line.startsWith("```")) {
      if (inCode) flushCode();
      else {
        flushList();
        inCode = true;
        codeLanguage = line.slice(3).trim().replace(/[^a-z0-9_-]/gi, "");
      }
      return;
    }
    if (inCode) {
      code.push(line);
      return;
    }
    if (line.startsWith("- ")) {
      list.push(line.slice(2));
      return;
    }
    flushList();
    if (!line.trim()) return;
    if (line.startsWith("### ")) output.push(<h3 key={index}>{line.slice(4)}</h3>);
    else if (line.startsWith("## ")) output.push(<h2 key={index}>{line.slice(3)}</h2>);
    else if (/^\d+\.\s/.test(line)) output.push(<p key={index} className="numbered-line">{inline(line)}</p>);
    else output.push(<p key={index}>{inline(line)}</p>);
  });
  if (inCode) flushCode();
  flushList();
  return <div className="markdown-body">{output}</div>;
}
