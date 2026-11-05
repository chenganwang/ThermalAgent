import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './MarkdownContent.css';

export default function MarkdownContent({ children }) {
  // GFM adds report tables; keep ReactMarkdown's raw-HTML and URL safety defaults.
  return <div className="markdown-content"><ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown></div>;
}
