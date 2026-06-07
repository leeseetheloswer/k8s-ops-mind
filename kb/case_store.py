"""
SQLite-backed fault case store.

Schema:
  fault_cases(id, created_at, symptom, root_cause, solution,
              resource_kind, resource_name, namespace, keywords)

Search is keyword-based (LIKE scoring). Upgrading to semantic search
only requires replacing `search_cases()` — the rest of the API stays the same.
"""
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "kb.db"

_STOPWORDS = {
    # Chinese
    '的', '了', '是', '在', '有', '和', '到', '这', '个', '我', '你', '他',
    '她', '它', '们', '就', '都', '而', '与', '对', '为', '以', '其',
    # English
    'the', 'a', 'an', 'is', 'of', 'to', 'in', 'it', 'be', 'as',
    'at', 'by', 'for', 'or', 'on',
}


@dataclass
class FaultCase:
    id: int
    created_at: str
    symptom: str
    root_cause: str
    solution: str
    resource_kind: str
    resource_name: str
    namespace: str
    keywords: str


# ── Internal helpers ─────────────────────────────────────────────────── #

def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def make_keywords(text: str) -> str:
    """Extract indexable tokens from free text."""
    tokens = re.findall(r'[一-鿿]{2,}|[a-zA-Z][a-zA-Z0-9\-]*', text)
    return ' '.join(t.lower() for t in tokens if t.lower() not in _STOPWORDS)


# ── Public API ───────────────────────────────────────────────────────── #

def init_db() -> None:
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS fault_cases (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
                symptom       TEXT    NOT NULL,
                root_cause    TEXT    NOT NULL,
                solution      TEXT    NOT NULL,
                resource_kind TEXT    NOT NULL DEFAULT '',
                resource_name TEXT    NOT NULL DEFAULT '',
                namespace     TEXT    NOT NULL DEFAULT '',
                keywords      TEXT    NOT NULL DEFAULT ''
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_kw ON fault_cases(keywords)")


def save_case(
    symptom: str,
    root_cause: str,
    solution: str,
    resource_kind: str = '',
    resource_name: str = '',
    namespace: str = '',
) -> int:
    kw = make_keywords(
        f"{symptom} {root_cause} {solution} {resource_kind} {resource_name}"
    )
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO fault_cases
               (symptom, root_cause, solution, resource_kind, resource_name, namespace, keywords)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (symptom, root_cause, solution, resource_kind, resource_name, namespace, kw),
        )
        return cur.lastrowid


def search_cases(query: str, limit: int = 3) -> list[FaultCase]:
    terms = make_keywords(query).split()
    if not terms:
        return []

    # Score = number of matching keyword terms; order by score DESC then recency DESC
    score_expr = ' + '.join(
        f"(CASE WHEN keywords LIKE ? THEN 1 ELSE 0 END)" for _ in terms
    )
    where_clause = ' OR '.join("keywords LIKE ?" for _ in terms)
    like_params = [f'%{t}%' for t in terms]

    with _conn() as c:
        rows = c.execute(
            f"""SELECT *, ({score_expr}) AS _score
                FROM fault_cases
                WHERE {where_clause}
                ORDER BY _score DESC, created_at DESC
                LIMIT ?""",
            like_params + like_params + [limit],
        ).fetchall()

    return [
        FaultCase(**{k: row[k] for k in row.keys() if k != '_score'})
        for row in rows
    ]


def format_cases_for_context(cases: list[FaultCase]) -> str:
    """Format cases as a context block to prepend to the user's message."""
    if not cases:
        return ""
    lines = ["[历史案例参考 — 仅供 LLM 参考，请结合实际情况判断]"]
    for i, c in enumerate(cases, 1):
        resource = ""
        if c.resource_kind:
            resource = f"  资源：{c.resource_kind}"
            if c.resource_name:
                resource += f" {c.namespace}/{c.resource_name}" if c.namespace else f" {c.resource_name}"
            resource += "\n"
        lines.append(
            f"\n--- 案例 {i}（{c.created_at}）---\n"
            f"  现象：{c.symptom}\n"
            f"{resource}"
            f"  根因：{c.root_cause}\n"
            f"  处置：{c.solution}"
        )
    lines.append("\n--- 历史案例结束 ---\n")
    return '\n'.join(lines)
