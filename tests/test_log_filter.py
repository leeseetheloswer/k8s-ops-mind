from utils.log_filter import filter_logs_for_llm


def _make_log(*lines):
    return "\n".join(lines)


class TestFilterLogsForLlm:
    def test_no_signal_returns_tail(self):
        log = _make_log(*[f"INFO normal line {i}" for i in range(20)])
        result = filter_logs_for_llm(log)
        assert "未发现" in result
        assert "末尾" in result

    def test_error_line_extracted(self):
        log = _make_log(
            "INFO start",
            "INFO step 1",
            "ERROR something went wrong",
            "INFO recovered",
            "INFO end",
        )
        result = filter_logs_for_llm(log, context_lines=1)
        assert "ERROR something went wrong" in result
        assert "INFO step 1" in result   # context before
        assert "INFO recovered" in result  # context after

    def test_lines_outside_context_omitted(self):
        # Two errors far apart: gap marker should appear between their context windows
        lines = [f"INFO line {i}" for i in range(40)]
        lines[5]  = "ERROR first"
        lines[35] = "ERROR second"
        log = _make_log(*lines)
        result = filter_logs_for_llm(log, context_lines=2)
        assert "INFO line 0" not in result   # before first context window
        assert "ERROR first" in result
        assert "ERROR second" in result
        assert "省略" in result              # gap between the two windows

    def test_duplicate_folding(self):
        repeated = ["ERROR connection refused"] * 10
        log = _make_log("INFO start", *repeated, "INFO end")
        result = filter_logs_for_llm(log, context_lines=0, max_duplicates=3)
        assert result.count("ERROR connection refused") == 3
        assert "折叠" in result
        assert "10" in result   # total count mentioned

    def test_exception_keyword_triggers(self):
        log = _make_log("INFO ok", "java.lang.NullPointerException: null", "INFO after")
        result = filter_logs_for_llm(log, context_lines=0)
        assert "NullPointerException" in result

    def test_warn_keyword_triggers(self):
        log = _make_log("INFO ok", "WARN disk usage high", "INFO ok")
        result = filter_logs_for_llm(log, context_lines=0)
        assert "WARN disk usage high" in result

    def test_error_string_returned_as_is(self):
        err = "Error: pods not found"
        assert filter_logs_for_llm(err) == err

    def test_empty_log_returned_as_is(self):
        assert filter_logs_for_llm("") == ""

    def test_header_shows_total_line_count(self):
        lines = [f"INFO {i}" for i in range(50)]
        lines[25] = "ERROR mid"
        result = filter_logs_for_llm(_make_log(*lines))
        assert "51" in result or "50" in result  # total lines in header

    def test_context_does_not_exceed_bounds(self):
        log = _make_log("ERROR first line")   # signal at line 0
        result = filter_logs_for_llm(log, context_lines=5)
        assert "ERROR first line" in result   # no index error

    def test_multiple_signals_merged(self):
        log = _make_log(
            *["INFO ok"] * 5,
            "ERROR first",
            *["INFO ok"] * 5,
            "WARN second",
            *["INFO ok"] * 5,
        )
        result = filter_logs_for_llm(log, context_lines=1)
        assert "ERROR first" in result
        assert "WARN second" in result
