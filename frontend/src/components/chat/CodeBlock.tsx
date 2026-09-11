import hljs from "highlight.js/lib/core";
import bash from "highlight.js/lib/languages/bash";
import c from "highlight.js/lib/languages/c";
import cpp from "highlight.js/lib/languages/cpp";
import css from "highlight.js/lib/languages/css";
import diff from "highlight.js/lib/languages/diff";
import dockerfile from "highlight.js/lib/languages/dockerfile";
import go from "highlight.js/lib/languages/go";
import ini from "highlight.js/lib/languages/ini";
import java from "highlight.js/lib/languages/java";
import javascript from "highlight.js/lib/languages/javascript";
import json from "highlight.js/lib/languages/json";
import markdown from "highlight.js/lib/languages/markdown";
import powershell from "highlight.js/lib/languages/powershell";
import python from "highlight.js/lib/languages/python";
import rust from "highlight.js/lib/languages/rust";
import sql from "highlight.js/lib/languages/sql";
import typescript from "highlight.js/lib/languages/typescript";
import xml from "highlight.js/lib/languages/xml";
import yaml from "highlight.js/lib/languages/yaml";
import { useMemo, useState } from "react";
import "highlight.js/styles/github-dark.css";

import { copyText } from "../../lib/clipboard";
import { cn } from "../../lib/format";

// Registering the languages the console actually shows keeps the bundle small.
const LANGUAGES = {
  bash,
  c,
  cpp,
  css,
  diff,
  dockerfile,
  go,
  ini,
  java,
  javascript,
  json,
  markdown,
  powershell,
  python,
  rust,
  sql,
  typescript,
  xml,
  yaml,
};

for (const [name, definition] of Object.entries(LANGUAGES)) {
  hljs.registerLanguage(name, definition);
}
hljs.registerAliases(["ts"], { languageName: "typescript" });
hljs.registerAliases(["js", "jsx", "mjs", "cjs"], { languageName: "javascript" });
hljs.registerAliases(["tsx"], { languageName: "typescript" });
hljs.registerAliases(["sh", "shell", "zsh"], { languageName: "bash" });
hljs.registerAliases(["html", "svg"], { languageName: "xml" });
hljs.registerAliases(["toml"], { languageName: "ini" });
hljs.registerAliases(["py"], { languageName: "python" });
hljs.registerAliases(["yml"], { languageName: "yaml" });
hljs.registerAliases(["ps1"], { languageName: "powershell" });
hljs.registerAliases(["md"], { languageName: "markdown" });

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

export function highlight(code: string, language?: string): string {
  try {
    if (language && hljs.getLanguage(language)) {
      return hljs.highlight(code, { language, ignoreIllegals: true }).value;
    }
    return hljs.highlightAuto(code).value;
  } catch {
    return escapeHtml(code);
  }
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      data-testid="copy-button"
      onClick={() => {
        void copyText(text).then((ok) => {
          setCopied(ok);
          window.setTimeout(() => setCopied(false), 1500);
        });
      }}
      className="rounded-md border border-edge px-2 py-0.5 text-[11px] text-slate-400 hover:border-accent hover:text-slate-200"
    >
      {copied ? "Copied" : label}
    </button>
  );
}

/** Fenced code with syntax highlighting, line numbers and a copy button. */
export function CodeBlock({
  code,
  language,
  filename,
  showLineNumbers = true,
}: {
  code: string;
  language?: string;
  filename?: string;
  showLineNumbers?: boolean;
}) {
  const html = useMemo(() => highlight(code, language), [code, language]);
  const lines = useMemo(() => code.replace(/\n$/, "").split("\n"), [code]);

  return (
    <div data-testid="code-block" className="my-2 overflow-hidden rounded-xl border border-edge bg-[#0b0e13]">
      <div className="flex items-center justify-between gap-2 border-b border-edge bg-panel px-3 py-1">
        <span className="truncate text-[11px] text-slate-400">
          {filename ?? language ?? "code"}
        </span>
        <CopyButton text={code} />
      </div>
      <div className="scroll-thin flex max-h-96 overflow-auto text-[12px] leading-5">
        {showLineNumbers && (
          <div
            aria-hidden="true"
            className="select-none border-r border-edge px-2 py-2 text-right font-mono text-slate-600"
          >
            {lines.map((_, index) => (
              <div key={index}>{index + 1}</div>
            ))}
          </div>
        )}
        <pre className="scroll-thin flex-1 overflow-x-auto px-3 py-2 font-mono">
          <code data-testid="code-block-body" dangerouslySetInnerHTML={{ __html: html }} />
        </pre>
      </div>
    </div>
  );
}

export function InlineCode({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <code
      className={cn(
        "rounded bg-panelAlt px-1 py-0.5 font-mono text-[12px] text-slate-200",
        className,
      )}
    >
      {children}
    </code>
  );
}
