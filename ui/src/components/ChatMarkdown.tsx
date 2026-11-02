import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface ChatMarkdownProps {
  content: string;
}

export function ChatMarkdown({ content }: ChatMarkdownProps) {
  return (
    <div className="chat-markdown min-w-0">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          table: ({ children, className }) => (
            <div className="chat-table-scroll" role="region" aria-label="回复表格" tabIndex={0}>
              <table className={className}>{children}</table>
            </div>
          ),
          a: ({ children, href, title, className }) => (
            <a href={href} title={title} className={className} target="_blank" rel="noopener noreferrer">{children}</a>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
