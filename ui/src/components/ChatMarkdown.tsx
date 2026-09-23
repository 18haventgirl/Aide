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
          table: ({ node: _node, ...props }) => (
            <div className="chat-table-scroll" role="region" aria-label="回复表格" tabIndex={0}>
              <table {...props} />
            </div>
          ),
          a: ({ node: _node, ...props }) => (
            <a {...props} target="_blank" rel="noopener noreferrer" />
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
