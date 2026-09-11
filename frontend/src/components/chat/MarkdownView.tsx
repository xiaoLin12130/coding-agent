import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { CodeBlock, InlineCode } from "./CodeBlock";

/**
 * Markdown rendering for assistant/tool messages: GFM tables and lists, code
 * fences highlighted, inline code styled. Raw HTML is never rendered
 * (react-markdown default), so message content stays DATA.
 */
export function MarkdownView({ content }: { content: string }) {
  return (
    <div data-testid="markdown" className="markdown-body text-sm leading-relaxed">
      <Markdown
        remarkPlugins={[remarkGfm]}
        components={{
          pre({ children }) {
            return <>{children}</>;
          },
          code({ className, children }) {
            const text = String(children ?? "").replace(/\n$/, "");
            const match = /language-([\w-]+)/.exec(className ?? "");
            if (match) {
              return <CodeBlock code={text} language={match[1]} />;
            }
            return <InlineCode>{children}</InlineCode>;
          },
          a({ href, children }) {
            return (
              <a
                href={href}
                target="_blank"
                rel="noreferrer noopener"
                className="text-accent underline decoration-dotted"
              >
                {children}
              </a>
            );
          },
          table({ children }) {
            return (
              <div className="scroll-thin my-2 overflow-x-auto">
                <table className="w-full border-collapse text-xs">{children}</table>
              </div>
            );
          },
          th({ children }) {
            return <th className="border border-edge bg-panelAlt px-2 py-1 text-left">{children}</th>;
          },
          td({ children }) {
            return <td className="border border-edge px-2 py-1 align-top">{children}</td>;
          },
          ul({ children }) {
            return <ul className="my-2 list-disc pl-5">{children}</ul>;
          },
          ol({ children }) {
            return <ol className="my-2 list-decimal pl-5">{children}</ol>;
          },
          p({ children }) {
            return <p className="my-1">{children}</p>;
          },
        }}
      >
        {content}
      </Markdown>
    </div>
  );
}
