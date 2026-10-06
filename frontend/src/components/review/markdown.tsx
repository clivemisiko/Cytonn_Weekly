import ReactMarkdown from "react-markdown";
import { cn } from "cn";

/**
 * The drafted text is markdown (bold headline, inline hyperlink citations, bold-italic outlook).
 * react-markdown renders no raw HTML and drops unsafe URL schemes; links open in a new tab.
 */
export function Markdown({ children, className }: { children: string; className?: string }) {
  return (
    <div className={cn("space-y-3", className)}>
      <ReactMarkdown
        components={{
          p: ({ children: c }) => <p>{c}</p>,
          a: ({ href, children: c }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-link underline decoration-link/40 underline-offset-2 transition-colors hover:decoration-link"
            >
              {c}
            </a>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
