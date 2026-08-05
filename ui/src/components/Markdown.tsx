/*
 * Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

"use client";

import React from "react";

/**
 * Dependency-free Markdown renderer for agent responses.
 *
 * Deliberately self-contained (no react-markdown / remark) so the customer /
 * security-review build adds no third-party supply-chain surface and the
 * container `npm ci` needs no lockfile change. Handles the subset the agents
 * emit: ATX headings, bold/italic/strike, inline + fenced code, GFM tables,
 * blockquotes, ordered/unordered lists, horizontal rules and links. All output
 * is built as React nodes (no dangerouslySetInnerHTML), so input is never
 * interpreted as HTML.
 */

type Token =
  | { kind: "code"; text: string }
  | { kind: "bold"; text: string }
  | { kind: "italic"; text: string }
  | { kind: "strike"; text: string }
  | { kind: "link"; label: string; href: string }
  | { kind: "text"; text: string };

const INLINE_RE =
  /(`[^`]+`)|(\*\*[\s\S]+?\*\*)|(__[\s\S]+?__)|(~~[\s\S]+?~~)|(\*[^*\n]+?\*)|(_[^_\n]+?_)|(\[[^\]]+\]\([^)\s]+\))/;

function tokenizeInline(input: string): Token[] {
  const tokens: Token[] = [];
  let rest = input;
  while (rest.length > 0) {
    const m = INLINE_RE.exec(rest);
    if (!m || m.index === undefined) {
      tokens.push({ kind: "text", text: rest });
      break;
    }
    if (m.index > 0) tokens.push({ kind: "text", text: rest.slice(0, m.index) });
    const tok = m[0];
    if (tok.startsWith("`")) {
      tokens.push({ kind: "code", text: tok.slice(1, -1) });
    } else if (tok.startsWith("**")) {
      tokens.push({ kind: "bold", text: tok.slice(2, -2) });
    } else if (tok.startsWith("__")) {
      tokens.push({ kind: "bold", text: tok.slice(2, -2) });
    } else if (tok.startsWith("~~")) {
      tokens.push({ kind: "strike", text: tok.slice(2, -2) });
    } else if (tok.startsWith("[")) {
      const lm = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(tok);
      if (lm) tokens.push({ kind: "link", label: lm[1], href: lm[2] });
      else tokens.push({ kind: "text", text: tok });
    } else if (tok.startsWith("*") || tok.startsWith("_")) {
      tokens.push({ kind: "italic", text: tok.slice(1, -1) });
    } else {
      tokens.push({ kind: "text", text: tok });
    }
    rest = rest.slice(m.index + tok.length);
  }
  return tokens;
}

function renderInline(input: string, keyPrefix: string): React.ReactNode[] {
  return tokenizeInline(input).map((t, i) => {
    const key = `${keyPrefix}-${i}`;
    switch (t.kind) {
      case "code":
        return (
          <code
            key={key}
            className="rounded bg-slate-900/80 px-1.5 py-0.5 font-mono text-[12px] text-emerald-300"
          >
            {t.text}
          </code>
        );
      case "bold":
        return (
          <strong key={key} className="font-semibold text-slate-50">
            {renderInline(t.text, key)}
          </strong>
        );
      case "italic":
        return (
          <em key={key} className="italic">
            {renderInline(t.text, key)}
          </em>
        );
      case "strike":
        return (
          <span key={key} className="line-through text-slate-400">
            {renderInline(t.text, key)}
          </span>
        );
      case "link":
        return (
          <a
            key={key}
            href={t.href}
            target="_blank"
            rel="noreferrer"
            className="text-blue-400 underline decoration-blue-400/40 underline-offset-2 hover:text-blue-300"
          >
            {renderInline(t.label, key)}
          </a>
        );
      default:
        return <React.Fragment key={key}>{t.text}</React.Fragment>;
    }
  });
}

function splitRow(line: string): string[] {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|")) s = s.slice(0, -1);
  return s.split("|").map((c) => c.trim());
}

const isTableSep = (line: string) =>
  /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line);
const isHr = (line: string) => /^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line);
const isUl = (line: string) => /^\s*[-*+]\s+/.test(line);
const isOl = (line: string) => /^\s*\d+\.\s+/.test(line);

export default function Markdown({ content }: { content: string }) {
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  const blocks: React.ReactNode[] = [];
  let i = 0;
  let key = 0;
  const nk = () => `b${key++}`;

  while (i < lines.length) {
    const line = lines[i];

    // Blank line
    if (line.trim() === "") {
      i++;
      continue;
    }

    // Fenced code block
    const fence = /^\s*```(\w+)?\s*$/.exec(line);
    if (fence) {
      const lang = fence[1];
      const buf: string[] = [];
      i++;
      while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) {
        buf.push(lines[i]);
        i++;
      }
      i++; // consume closing fence
      blocks.push(
        <pre
          key={nk()}
          className="my-2 overflow-x-auto rounded-lg border border-slate-700 bg-slate-950 p-3"
        >
          {lang && (
            <div className="mb-1 text-[10px] font-medium uppercase tracking-wide text-slate-500">
              {lang}
            </div>
          )}
          <code className="font-mono text-[12px] leading-relaxed text-slate-100 whitespace-pre">
            {buf.join("\n")}
          </code>
        </pre>
      );
      continue;
    }

    // Table (header row + separator row)
    if (
      line.includes("|") &&
      i + 1 < lines.length &&
      isTableSep(lines[i + 1])
    ) {
      const header = splitRow(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim() !== "") {
        rows.push(splitRow(lines[i]));
        i++;
      }
      blocks.push(
        <div key={nk()} className="my-2 overflow-x-auto">
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr>
                {header.map((h, hi) => (
                  <th
                    key={hi}
                    className="border border-slate-700 bg-slate-900/80 px-2.5 py-1.5 text-left font-semibold text-slate-200"
                  >
                    {renderInline(h, `th${hi}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, ri) => (
                <tr key={ri} className={ri % 2 ? "bg-slate-800/40" : ""}>
                  {header.map((_, ci) => (
                    <td
                      key={ci}
                      className="border border-slate-700 px-2.5 py-1.5 align-top text-slate-300"
                    >
                      {renderInline(r[ci] ?? "", `td${ri}-${ci}`)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      continue;
    }

    // Horizontal rule
    if (isHr(line)) {
      blocks.push(<hr key={nk()} className="my-3 border-slate-700" />);
      i++;
      continue;
    }

    // Heading
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) {
      const level = h[1].length;
      const cls =
        level <= 1
          ? "mt-3 mb-1.5 text-base font-bold text-slate-50"
          : level === 2
          ? "mt-3 mb-1.5 text-sm font-bold text-slate-100"
          : "mt-2 mb-1 text-sm font-semibold text-slate-200";
      const Tag = (`h${Math.min(level, 6)}`) as keyof React.JSX.IntrinsicElements;
      blocks.push(
        <Tag key={nk()} className={cls}>
          {renderInline(h[2], nk())}
        </Tag>
      );
      i++;
      continue;
    }

    // Blockquote
    if (/^\s*>\s?/.test(line)) {
      const buf: string[] = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
        buf.push(lines[i].replace(/^\s*>\s?/, ""));
        i++;
      }
      blocks.push(
        <blockquote
          key={nk()}
          className="my-2 rounded-r border-l-2 border-blue-500/60 bg-slate-900/40 py-1.5 pl-3 pr-2 text-slate-300"
        >
          {renderInline(buf.join(" "), nk())}
        </blockquote>
      );
      continue;
    }

    // Unordered list
    if (isUl(line)) {
      const items: string[] = [];
      while (i < lines.length && isUl(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*+]\s+/, ""));
        i++;
      }
      blocks.push(
        <ul key={nk()} className="my-1.5 list-disc space-y-0.5 pl-5">
          {items.map((it, ii) => (
            <li key={ii} className="text-slate-200">
              {renderInline(it, `li${ii}`)}
            </li>
          ))}
        </ul>
      );
      continue;
    }

    // Ordered list
    if (isOl(line)) {
      const items: string[] = [];
      while (i < lines.length && isOl(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+\.\s+/, ""));
        i++;
      }
      blocks.push(
        <ol key={nk()} className="my-1.5 list-decimal space-y-0.5 pl-5">
          {items.map((it, ii) => (
            <li key={ii} className="text-slate-200">
              {renderInline(it, `oli${ii}`)}
            </li>
          ))}
        </ol>
      );
      continue;
    }

    // Paragraph: gather consecutive plain lines
    const para: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !/^\s*```/.test(lines[i]) &&
      !isHr(lines[i]) &&
      !/^(#{1,6})\s+/.test(lines[i]) &&
      !/^\s*>\s?/.test(lines[i]) &&
      !isUl(lines[i]) &&
      !isOl(lines[i]) &&
      !(lines[i].includes("|") && i + 1 < lines.length && isTableSep(lines[i + 1]))
    ) {
      para.push(lines[i]);
      i++;
    }
    if (para.length) {
      blocks.push(
        <p key={nk()} className="my-1.5 text-sm leading-relaxed text-slate-200">
          {para.map((pl, pi) => (
            <React.Fragment key={pi}>
              {pi > 0 && <br />}
              {renderInline(pl, `p${pi}`)}
            </React.Fragment>
          ))}
        </p>
      );
    }
  }

  return <div className="markdown-body">{blocks}</div>;
}
