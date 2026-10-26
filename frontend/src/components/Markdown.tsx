import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** Renders model output as formatted markdown (headings, lists, tables, code). */
export function Markdown({ children }: { children: string }) {
  return (
    <div className="kai-md text-left break-words">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: (p) => <h1 className="mb-2 mt-3 text-base font-semibold" style={{ color: "var(--kai-hud)" }} {...p} />,
          h2: (p) => <h2 className="mb-2 mt-3 text-[15px] font-semibold" style={{ color: "var(--kai-hud)" }} {...p} />,
          h3: (p) => <h3 className="mb-1 mt-3 text-sm font-semibold" style={{ color: "var(--kai-hud)" }} {...p} />,
          h4: (p) => <h4 className="mb-1 mt-2 text-sm font-semibold" {...p} />,
          p: (p) => <p className="my-2 leading-relaxed" {...p} />,
          ul: (p) => <ul className="my-2 ml-5 list-disc space-y-1" {...p} />,
          ol: (p) => <ol className="my-2 ml-5 list-decimal space-y-1" {...p} />,
          li: (p) => <li className="leading-relaxed" {...p} />,
          strong: (p) => <strong className="font-semibold text-ink" {...p} />,
          em: (p) => <em className="italic" {...p} />,
          hr: () => <hr className="my-3 border-line" />,
          a: (p) => <a className="underline" style={{ color: "var(--kai-hud)" }} target="_blank" rel="noreferrer" {...p} />,
          blockquote: (p) => <blockquote className="my-2 border-l-2 border-line pl-3 text-muted" {...p} />,
          pre: (p) => <pre className="my-2 max-h-80 overflow-auto rounded border border-line bg-panel-2 p-2 font-mono text-[12px]" {...p} />,
          code: ({ className, children: c, ...rest }) =>
            className ? (
              <code className={className} {...rest}>{c}</code>
            ) : (
              <code className="rounded bg-panel-2 px-1 py-0.5 font-mono text-[12px]" style={{ color: "var(--kai-hud)" }} {...rest}>{c}</code>
            ),
          table: (p) => <div className="my-2 overflow-x-auto"><table className="w-full border-collapse text-xs" {...p} /></div>,
          th: (p) => <th className="border border-line bg-panel-2 px-2 py-1 text-left font-semibold" {...p} />,
          td: (p) => <td className="border border-line px-2 py-1 align-top" {...p} />,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
