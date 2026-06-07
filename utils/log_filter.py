"""
Log preprocessing for LLM consumption.

Extracts signal lines (ERROR/WARN/Exception etc.), keeps context around them,
and folds runs of repeated lines.
"""
import re

# Lines containing any of these are "signal" lines worth keeping
_SIGNAL_RE = re.compile(
    r'(error|warn|warning|exception|traceback|panic|fatal|critical'
    r'|oomkilled|killed|crash|segfault|timeout|refused|unavailable)',
    re.IGNORECASE,
)

# Volatile parts to strip before comparing two lines for dedup
_TIMESTAMP_RE = re.compile(
    r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[\w.\+\-:]*'   # ISO timestamp
    r'|\d{2}:\d{2}:\d{2}[.\d]*'                              # HH:MM:SS
)
_HEX_RE   = re.compile(r'0x[0-9a-fA-F]{4,}')
_UUID_RE  = re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', re.IGNORECASE)
_NUM_RE   = re.compile(r'\b\d{4,}\b')   # long numbers (PIDs, ports, offsets)


def _normalize(line: str) -> str:
    """Strip volatile parts so structurally identical lines compare equal."""
    s = _TIMESTAMP_RE.sub('', line)
    s = _HEX_RE.sub('0xXX', s)
    s = _UUID_RE.sub('UUID', s)
    s = _NUM_RE.sub('N', s)
    return s.strip()


def _fold_duplicates(lines: list[str], max_keep: int) -> list[str]:
    """Collapse consecutive normalized-identical lines."""
    result: list[str] = []
    i = 0
    while i < len(lines):
        norm = _normalize(lines[i])
        j = i + 1
        while j < len(lines) and _normalize(lines[j]) == norm:
            j += 1
        count = j - i
        if count > max_keep:
            result.extend(lines[i : i + max_keep])
            result.append(f"    ... [同一错误重复 {count} 次，已折叠 {count - max_keep} 条]")
        else:
            result.extend(lines[i:j])
        i = j
    return result


def filter_logs_for_llm(
    raw: str,
    context_lines: int = 3,
    max_duplicates: int = 3,
) -> str:
    """
    Preprocess raw pod log text before sending to an LLM:

    1. Extract lines matching ERROR/WARN/Exception/etc.
    2. Keep `context_lines` lines before and after each match.
    3. Fold runs of repeated (normalized) lines, keeping at most `max_duplicates`.
    4. Prepend a summary header with total line count.

    If the log is an error string (K8s API failure) it is returned as-is.
    If no signal lines are found, the last 10 lines are returned as a tail.
    """
    if not raw or raw.startswith("Error:"):
        return raw

    lines = raw.splitlines()
    total = len(lines)

    signal_idx = [i for i, ln in enumerate(lines) if _SIGNAL_RE.search(ln)]

    if not signal_idx:
        tail = lines[-min(10, total):]
        return (
            f"[共 {total} 行，未发现 ERROR/WARN/Exception，展示末尾 {len(tail)} 行]\n"
            + "\n".join(tail)
        )

    # Expand each signal line to a context window
    keep: set[int] = set()
    for idx in signal_idx:
        for j in range(max(0, idx - context_lines), min(total, idx + context_lines + 1)):
            keep.add(j)

    # Assemble output in order, inserting gap markers
    selected: list[str] = []
    prev = -1
    for idx in sorted(keep):
        if prev >= 0 and idx > prev + 1:
            selected.append(f"    ... [{idx - prev - 1} 行省略] ...")
        selected.append(lines[idx])
        prev = idx

    folded = _fold_duplicates(selected, max_keep=max_duplicates)

    header = (
        f"[共 {total} 行日志，发现 {len(signal_idx)} 处异常信号，"
        f"已提取上下文 ±{context_lines} 行并折叠重复]\n"
    )
    return header + "\n".join(folded)
