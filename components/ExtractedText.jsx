"use client";

import { useState } from "react";
import { Checkbox } from "@/components/ui/checkbox";

const htmlHead = `<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{margin:0;padding:25px;font:14px/1.7 "Segoe UI",Arial,sans-serif;color:#334d4e;overflow-wrap:anywhere;white-space:pre-wrap}
table{border-collapse:collapse;white-space:normal;font-size:13px}
th,td{border:1px solid #d8e5e5;padding:8px 10px;text-align:left;vertical-align:top;min-width:120px;max-width:260px}
th{background:#edf3f3}pre{white-space:pre;overflow:auto}img{max-width:100%;height:auto}a{color:#00504e}
</style></head><body>`;

export default function ExtractedText({ text }) {
  const [html, setHtml] = useState(false);
  const content = text || "В документе не найден текст.";
  const htmlContent = content.split(/\r\n|\r|\n/).filter((line) => line.trim().length > 0).join("\n");
  return <>
    <label className="document-html-toggle">
      <Checkbox checked={html} onCheckedChange={(checked) => setHtml(checked === true)}/>
      <span>Просмотреть в .html</span>
    </label>
    {html
      ? <iframe className="document-html" title="Текст документа в HTML" sandbox="" referrerPolicy="no-referrer" srcDoc={`${htmlHead}${htmlContent}</body></html>`}/>
      : <pre className="document-text">{content}</pre>}
  </>;
}
