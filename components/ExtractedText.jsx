"use client";

import { useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Checkbox } from "@/components/ui/checkbox";

const markdownComponents = {
  a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>,
  img: ({ src, alt }) => <a href={src} target="_blank" rel="noopener noreferrer">{alt || "Изображение"}</a>,
  table: ({ children }) => <div className="document-markdown-table"><table>{children}</table></div>,
};

export default function ExtractedText({ text }) {
  const [markdown, setMarkdown] = useState(false);
  const content = text || "В документе не найден текст.";
  return <>
    <label className="document-markdown-toggle">
      <Checkbox checked={markdown} onCheckedChange={(checked) => setMarkdown(checked === true)}/>
      <span>Просмотреть в Markdown</span>
    </label>
    {markdown
      ? <div className="document-text document-markdown"><Markdown remarkPlugins={[remarkGfm]} skipHtml components={markdownComponents}>{content}</Markdown></div>
      : <pre className="document-text">{content}</pre>}
  </>;
}
