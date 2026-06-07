import styles from './Sidebar.module.css'

const TIPS = [
  '列出所有 Pod',
  '查看最近的异常事件',
  '帮我排查 CrashLoopBackOff',
  '把 nginx 扩容到 3 个副本',
  '查看 default 命名空间的 Service',
]

export default function Sidebar({ health, onSend }) {
  return (
    <aside className={styles.sidebar}>
      <section className={styles.section}>
        <h3 className={styles.sectionTitle}>集群信息</h3>
        <div className={styles.item}>
          <span className={styles.label}>命名空间</span>
          <span className={styles.value}>default</span>
        </div>
        <div className={styles.item}>
          <span className={styles.label}>Provider</span>
          <span className={styles.value}>{health?.provider ?? '—'}</span>
        </div>
        <div className={styles.item}>
          <span className={styles.label}>状态</span>
          <span className={`${styles.value} ${health?.status === 'ok' ? styles.ok : styles.err}`}>
            {health?.status === 'ok' ? '● 正常' : '● 离线'}
          </span>
        </div>
      </section>

      <section className={styles.section}>
        <h3 className={styles.sectionTitle}>快速提问</h3>
        <ul className={styles.tips}>
          {TIPS.map(tip => (
            <li key={tip} className={styles.tip}
              onClick={() => onSend(tip)}>
              {tip}
            </li>
          ))}
        </ul>
      </section>
    </aside>
  )
}
