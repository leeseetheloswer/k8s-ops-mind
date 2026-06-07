import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import styles from './ChatMessage.module.css'

function TypingDots() {
  return (
    <span className={styles.typing}>
      <span /><span /><span />
    </span>
  )
}

const mdComponents = {
  code({ node, inline, className, children, ...props }) {
    const match = /language-(\w+)/.exec(className || '')
    return !inline && match ? (
      <SyntaxHighlighter style={oneDark} language={match[1]} PreTag="div" {...props}>
        {String(children).replace(/\n$/, '')}
      </SyntaxHighlighter>
    ) : (
      <code className={styles.inlineCode} {...props}>{children}</code>
    )
  },
  table({ children }) {
    return <div className={styles.tableWrapper}><table>{children}</table></div>
  },
}

function AlertBubble({ alert, content }) {
  return (
    <div className={`${styles.row} ${styles.alertRow}`}>
      <div className={`${styles.avatar} ${styles.alertAvatar}`}>⚠</div>
      <div className={`${styles.bubble} ${styles.alertBubble}`}>
        <p className={styles.alertSummary}>{alert?.summary}</p>
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
          {content}
        </ReactMarkdown>
        {alert?.timestamp && (
          <p className={styles.alertTime}>
            {new Date(alert.timestamp).toLocaleTimeString()}
            {' · '}
            {alert.kind} {alert.namespace ? `${alert.namespace}/` : ''}{alert.name}
          </p>
        )}
      </div>
    </div>
  )
}

export default function ChatMessage({ role, content, loading, error, alert }) {
  if (role === 'alert') return <AlertBubble alert={alert} content={content} />

  const isUser = role === 'user'
  return (
    <div className={`${styles.row} ${isUser ? styles.userRow : styles.assistantRow}`}>
      <div className={styles.avatar}>
        {isUser ? '你' : '⎈'}
      </div>
      <div className={`${styles.bubble} ${isUser ? styles.userBubble : styles.assistantBubble} ${error ? styles.errorBubble : ''}`}>
        {loading ? (
          <TypingDots />
        ) : isUser ? (
          <p className={styles.plainText}>{content}</p>
        ) : (
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
            {content}
          </ReactMarkdown>
        )}
      </div>
    </div>
  )
}
