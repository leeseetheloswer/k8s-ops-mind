import styles from './Header.module.css'

export default function Header({ health, onReset }) {
  const ok = health?.status === 'ok'
  return (
    <header className={styles.header}>
      <div className={styles.left}>
        <span className={styles.logo}>⎈</span>
        <span className={styles.title}>K8s 运维助手</span>
        {health && (
          <span className={`${styles.badge} ${ok ? styles.ok : styles.err}`}>
            {ok ? health.provider : '离线'}
          </span>
        )}
      </div>
      <button className={styles.resetBtn} onClick={onReset} title="清空对话">
        重置对话
      </button>
    </header>
  )
}
