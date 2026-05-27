import type { ReactNode } from "react";
import type { ChatMessage } from "../../types";

function renderInlineMarkdown(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|<br\s*\/?>)/gi).map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    if (/^<br\s*\/?>$/i.test(part)) {
      return <br key={index} />;
    }
    return part;
  });
}

function renderMessageContent(content: string) {
  const blocks: ReactNode[] = [];
  const lines = content.split("\n");
  let listItems: string[] = [];
  let tableRows: string[][] = [];

  function flushList() {
    if (listItems.length === 0) return;
    blocks.push(
      <ul key={`list-${blocks.length}`} className="message-list">
        {listItems.map((item, index) => (
          <li key={index}>{renderInlineMarkdown(item)}</li>
        ))}
      </ul>
    );
    listItems = [];
  }

  function isTableSeparator(line: string) {
    return /^\|?[\s:-]+\|[\s|:-]+$/.test(line);
  }

  function isTableRow(line: string) {
    return (line.match(/\|/g)?.length ?? 0) >= 2;
  }

  function parseTableRow(line: string) {
    return line
      .trim()
      .replace(/^\|/, "")
      .replace(/\|$/, "")
      .split("|")
      .map((cell) => cell.trim());
  }

  function flushTable() {
    if (tableRows.length < 2) {
      tableRows = [];
      return;
    }

    const [headers, ...rows] = tableRows;
    blocks.push(
      <div key={`table-${blocks.length}`} className="message-table-wrap">
        <table className="message-table">
          <thead>
            <tr>
              {headers.map((header, index) => (
                <th key={index}>{renderInlineMarkdown(header)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((cell, cellIndex) => (
                  <td key={cellIndex}>{renderInlineMarkdown(cell)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
    tableRows = [];
  }

  lines.forEach((line) => {
    const trimmed = line.trim();
    if (!trimmed) {
      flushList();
      flushTable();
      return;
    }

    if (isTableRow(trimmed)) {
      if (isTableSeparator(trimmed)) return;
      flushList();
      tableRows.push(parseTableRow(trimmed));
      return;
    }

    if (trimmed.startsWith("- ")) {
      flushTable();
      listItems.push(trimmed.slice(2));
      return;
    }

    flushList();
    flushTable();
    blocks.push(<p key={`paragraph-${blocks.length}`}>{renderInlineMarkdown(trimmed)}</p>);
  });

  flushList();
  flushTable();
  return blocks;
}

export function MessageBubble({ message }: { message: ChatMessage }) {
  return (
    <div className={`message-row ${message.role}`}>
      <div className="message-bubble">
        {message.role === "assistant" && !message.content ? (
          <div className="answer-loading" aria-live="polite">
            <span className="loading-dot" />
            <span>Answer is loading</span>
          </div>
        ) : (
          <div className="message-content">{renderMessageContent(message.content)}</div>
        )}
      </div>
    </div>
  );
}
