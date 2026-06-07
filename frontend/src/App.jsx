import { useState, useEffect, useRef, useCallback } from 'react'
import Header from './components/Header.jsx'
import Sidebar from './components/Sidebar.jsx'
import ChatMessage from './components/ChatMessage.jsx'
import ChatInput from './components/ChatInput.jsx'
import ConfirmModal from './components/ConfirmModal.jsx'
import styles from './App.module.css'

const STORAGE_KEY = 'k8s_messages'

const WELCOME = {
  role: 'assistant',
  content: '你好！我是 K8s 运维助手，可以帮你查询集群状态、排查问题、执行运维操作。请问有什么需要帮忙的？',
}

function getSessionId() {
  let id = localStorage.getItem('k8s_session_id')
  if (!id) {
    id = crypto.randomUUID()
    localStorage.setItem('k8s_session_id', id)
  }
  return id
}

function loadMessages() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) return JSON.parse(saved)
  } catch {}
  return [WELCOME]
}

function saveMessages(msgs) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(msgs))
  } catch {}
}

export default function App() {
  const [messages, setMessages] = useState(loadMessages)
  const [loading, setLoading] = useState(false)
  const [health, setHealth] = useState(null)
  const [pendingAction, setPendingAction] = useState(null)  // {description}
  const sessionId = useRef(getSessionId())
  const bottomRef = useRef(null)

  useEffect(() => {
    fetch('/api/health')
      .then(r => r.json())
      .then(setHealth)
      .catch(() => setHealth({ status: 'error' }))
  }, [])

  useEffect(() => {
    saveMessages(messages)
  }, [messages])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const sendMessage = useCallback(async (text) => {
    const userMsg = { role: 'user', content: text }
    setMessages(prev => [...prev, userMsg])
    setLoading(true)

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: sessionId.current }),
      })
      const data = await res.json()
      if (data.pending_action) {
        setPendingAction(data.pending_action)
      }
      setMessages(prev => [...prev, { role: 'assistant', content: data.reply }])
    } catch {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: '⚠️ 请求失败，请检查后端服务是否正常运行。',
        error: true,
      }])
    } finally {
      setLoading(false)
    }
  }, [])

  const handleConfirm = useCallback(async (confirmed) => {
    setPendingAction(null)
    setLoading(true)
    try {
      const res = await fetch('/api/confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId.current, confirmed }),
      })
      const data = await res.json()
      if (data.pending_action) setPendingAction(data.pending_action)
      setMessages(prev => [...prev, { role: 'assistant', content: data.reply }])
    } catch {
      setMessages(prev => [...prev, { role: 'assistant', content: '⚠️ 请求失败。', error: true }])
    } finally {
      setLoading(false)
    }
  }, [])

  const reset = useCallback(async () => {
    await fetch(`/api/reset?session_id=${sessionId.current}`, { method: 'POST' })
    localStorage.removeItem(STORAGE_KEY)
    setMessages([WELCOME])
  }, [])

  return (
    <div className={styles.layout}>
      <Header health={health} onReset={reset} />
      <div className={styles.body}>
        <Sidebar health={health} onSend={sendMessage} />
        <main className={styles.main}>
          <div className={styles.messages}>
            {messages.map((msg, i) => (
              <ChatMessage key={i} role={msg.role} content={msg.content} error={msg.error} />
            ))}
            {loading && <ChatMessage role="assistant" content="" loading />}
            <div ref={bottomRef} />
          </div>
          <ChatInput onSend={sendMessage} disabled={loading || !!pendingAction} />
        </main>
      </div>
      {pendingAction && (
        <ConfirmModal
          description={pendingAction.description}
          onConfirm={() => handleConfirm(true)}
          onCancel={() => handleConfirm(false)}
        />
      )}
    </div>
  )
}
