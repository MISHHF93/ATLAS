import { Fragment, type ReactNode } from "react";

/** Minimal, safe Markdown renderer (no HTML injection): headings, lists, quotes, code fences, tables, inline code/bold/links. */
function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\[[^\]]+\]\([^)\s]+\))/g;
  let last = 0, m: RegExpExecArray | null, k = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const t = m[0];
    if (t.startsWith("`")) out.push(<code key={k++} className="ux-code">{t.slice(1, -1)}</code>);
    else if (t.startsWith("**")) out.push(<strong key={k++}>{t.slice(2, -2)}</strong>);
    else {
      const [, label, href] = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(t) ?? [];
      const safe = /^(https?:|\/|#)/.test(href ?? "");
      out.push(safe ? <a key={k++} className="ux-link" href={href} rel="noreferrer">{label}</a> : label);
    }
    last = m.index + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function Markdown({ source }: { source: string }) {
  const lines = source.replace(/\r/g, "").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0, k = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (/^```/.test(line)) {
      const buf: string[] = []; i++;
      while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
      i++; blocks.push(<pre key={k++} className="ux-md-pre">{buf.join("\n")}</pre>); continue;
    }
    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    if (h) { const L = Math.min(4, h[1].length + 1); const T = `h${L}` as "h2"; blocks.push(<T key={k++}>{inline(h[2])}</T>); i++; continue; }
    if (/^\s*\|/.test(line)) {
      const rows: string[][] = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) { if (!/^\s*\|[\s:|-]+\|\s*$/.test(lines[i])) rows.push(lines[i].trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim())); i++; }
      const [head, ...body] = rows;
      blocks.push(
        <div key={k++} className="ux-table-wrap"><table className="ux-table">
          <thead><tr>{head.map((c, j) => <th key={j} scope="col">{inline(c)}</th>)}</tr></thead>
          <tbody>{body.map((r, ri) => <tr key={ri}>{r.map((c, j) => <td key={j}>{inline(c)}</td>)}</tr>)}</tbody>
        </table></div>);
      continue;
    }
    if (/^\s*>/.test(line)) {
      const buf: string[] = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) buf.push(lines[i++].replace(/^\s*>\s?/, ""));
      blocks.push(<blockquote key={k++}>{inline(buf.join(" "))}</blockquote>); continue;
    }
    if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\./.test(line); const items: string[] = [];
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*([-*]|\d+\.)\s+/, ""));
      const L = ordered ? "ol" : "ul";
      blocks.push(<L key={k++}>{items.map((t, j) => <li key={j}>{inline(t)}</li>)}</L>); continue;
    }
    if (/^\s*(---|\*\*\*)\s*$/.test(line)) { blocks.push(<hr key={k++} />); i++; continue; }
    if (!line.trim()) { i++; continue; }
    const buf: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|\s*\||\s*>|\s*([-*]|\d+\.)\s)/.test(lines[i])) buf.push(lines[i++]);
    blocks.push(<p key={k++}>{inline(buf.join(" "))}</p>);
  }
  return <div className="ux-prose">{blocks.map((b, j) => <Fragment key={j}>{b}</Fragment>)}</div>;
}
