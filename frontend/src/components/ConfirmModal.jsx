import { useEffect } from 'react'
import styles from './ConfirmModal.module.css'

export default function ConfirmModal({ description, onConfirm, onCancel }) {
  useEffect(() => {
    function onKey(e) {
      if (e.key === 'Escape') onCancel()
      if (e.key === 'Enter')  onConfirm()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onConfirm, onCancel])

  return (
    <div className={styles.overlay} onClick={onCancel}>
      <div className={styles.modal} onClick={e => e.stopPropagation()}>
        <div className={styles.icon}>⚠️</div>
        <h2 className={styles.title}>危险操作确认</h2>
        <p className={styles.desc}>{description}</p>
        <p className={styles.hint}>此操作可能影响线上服务，请确认后执行。</p>
        <div className={styles.actions}>
          <button className={styles.cancelBtn} onClick={onCancel}>
            取消（Esc）
          </button>
          <button className={styles.confirmBtn} onClick={onConfirm}>
            确认执行（Enter）
          </button>
        </div>
      </div>
    </div>
  )
}
