import type { ReactNode } from "react";

type Props = { content: string };

function inline(text: string) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    return part;
  });
}

export function MarkdownLite({ content }: Props) {
  const lines = content.split("\n");
  const output: ReactNode[] = [];
  let list: string[] = [];

  function flushList() {
    if (!list.length) return;
    output.push(
      <ul key={`list-${output.length}`} className="answer-list">
        {list.map((item, i) => <li key={i}>{inline(item)}</li>)}
      </ul>,
    );
    list = [];
  }

  lines.forEach((line, index) => {
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
  flushList();
  return <div className="markdown-body">{output}</div>;
}
