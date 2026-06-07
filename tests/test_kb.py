"""
Tests for kb.case_store and kb.extractor.
"""
import pytest
import tempfile
import os
from unittest.mock import patch, MagicMock
from pathlib import Path


# ── case_store tests ────────────────────────────────────────────────── #

class TestMakeKeywords:
    def setup_method(self):
        from kb.case_store import make_keywords
        self.make_keywords = make_keywords

    def test_extracts_chinese_tokens(self):
        kw = self.make_keywords("内存溢出导致崩溃")
        assert "内存" in kw or "溢出" in kw

    def test_extracts_english_tokens(self, ):
        kw = self.make_keywords("OOMKilled CrashLoopBackOff error")
        assert "oomkilled" in kw
        assert "crashloopbackoff" in kw

    def test_filters_stopwords(self):
        kw = self.make_keywords("the a pod is the problem")
        assert " the " not in f" {kw} "
        assert "pod" in kw

    def test_empty_string(self):
        assert self.make_keywords("") == ""


class TestCaseStore:
    """Uses a temp DB path to avoid polluting the real data/kb.db."""

    @pytest.fixture(autouse=True)
    def tmp_db(self, tmp_path, monkeypatch):
        db_path = tmp_path / "test_kb.db"
        monkeypatch.setattr("kb.case_store.DB_PATH", db_path)
        from kb.case_store import init_db
        init_db()

    def test_save_and_retrieve(self):
        from kb.case_store import save_case, search_cases
        cid = save_case(
            symptom="Pod OOMKilled",
            root_cause="内存限制过低",
            solution="调高 resources.limits.memory",
            resource_kind="Pod",
            resource_name="nginx-abc",
            namespace="default",
        )
        assert cid > 0
        results = search_cases("OOMKilled")
        assert len(results) == 1
        assert results[0].symptom == "Pod OOMKilled"
        assert results[0].resource_name == "nginx-abc"

    def test_search_returns_empty_for_no_match(self):
        from kb.case_store import search_cases
        results = search_cases("xyzzy-nonexistent-term")
        assert results == []

    def test_search_scores_better_matches_first(self):
        from kb.case_store import save_case, search_cases
        save_case("CrashLoopBackOff内存不足", "内存限制", "调高内存")
        save_case("磁盘 IO 延迟", "存储问题", "检查 PVC")
        results = search_cases("内存 OOM CrashLoop")
        # first result should be the memory case
        assert "内存" in results[0].root_cause or "内存" in results[0].symptom

    def test_search_limit_respected(self):
        from kb.case_store import save_case, search_cases
        for i in range(5):
            save_case(f"error case {i}", "root", "fix", resource_name=f"pod-{i}")
        results = search_cases("error", limit=2)
        assert len(results) <= 2

    def test_format_cases_for_context_empty(self):
        from kb.case_store import format_cases_for_context
        assert format_cases_for_context([]) == ""

    def test_format_cases_includes_fields(self):
        from kb.case_store import save_case, search_cases, format_cases_for_context
        save_case(
            symptom="Deployment 副本数不足",
            root_cause="节点资源耗尽",
            solution="扩容节点",
            resource_kind="Deployment",
            resource_name="web",
            namespace="prod",
        )
        cases = search_cases("Deployment 副本")
        ctx = format_cases_for_context(cases)
        assert "Deployment 副本数不足" in ctx
        assert "节点资源耗尽" in ctx
        assert "扩容节点" in ctx
        assert "历史案例" in ctx


# ── extractor tests ─────────────────────────────────────────────────── #

class TestShouldExtract:
    def setup_method(self):
        from kb.extractor import should_extract
        self.should_extract = should_extract

    def _history(self, n=4):
        return [{"role": "user", "content": "q"}] * n

    def test_too_short_history(self):
        assert self.should_extract(self._history(2), "根因是内存泄漏，建议重启") is False

    def test_short_reply(self):
        assert self.should_extract(self._history(6), "好的") is False

    def test_diagnostic_keywords_trigger(self):
        reply = (
            "根因分析：Pod 内存不足导致 OOMKilled，建议调高 resources.limits.memory 到 512Mi，"
            "同时排查内存泄漏问题，可使用 kubectl top pod 观察内存增长趋势。"
        )
        assert len(reply) >= 80
        assert self.should_extract(self._history(6), reply) is True

    def test_non_diagnostic_reply(self):
        reply = "Pod nginx-abc 当前状态为 Running，所有容器运行正常，无重启记录，无告警事件。" * 3
        assert self.should_extract(self._history(6), reply) is False


class TestFmtHistory:
    def setup_method(self):
        from kb.extractor import _fmt_history
        self._fmt = _fmt_history

    def test_skips_system_messages(self):
        h = [{"role": "system", "content": "system prompt"}, {"role": "user", "content": "hello"}]
        result = self._fmt(h)
        assert "system prompt" not in result
        assert "[用户] hello" in result

    def test_handles_string_content(self):
        h = [
            {"role": "user", "content": "查询 Pod 状态"},
            {"role": "assistant", "content": "当前 Pod 状态正常"},
        ]
        result = self._fmt(h)
        assert "[用户] 查询 Pod 状态" in result
        assert "[助手] 当前 Pod 状态正常" in result

    def test_handles_list_content(self):
        h = [{"role": "user", "content": [{"type": "text", "text": "列出所有 Pod"}]}]
        result = self._fmt(h)
        assert "[用户] 列出所有 Pod" in result

    def test_caps_at_30_exchanges(self):
        h = [{"role": "user", "content": f"msg {i}"} for i in range(40)]
        result = self._fmt(h)
        lines = result.split('\n')
        assert len(lines) <= 30


class TestParseJson:
    def setup_method(self):
        from kb.extractor import _parse_json
        self._parse = _parse_json

    def test_plain_json(self):
        result = self._parse('{"has_conclusion": false}')
        assert result == {"has_conclusion": False}

    def test_json_in_code_fence(self):
        text = '```json\n{"has_conclusion": true, "symptom": "X"}\n```'
        result = self._parse(text)
        assert result["has_conclusion"] is True
        assert result["symptom"] == "X"

    def test_invalid_json_returns_none(self):
        result = self._parse("not json at all")
        assert result is None

    def test_json_embedded_in_text(self):
        text = 'Here is the answer: {"has_conclusion": true, "symptom": "test"} done.'
        result = self._parse(text)
        assert result is not None
        assert result["has_conclusion"] is True


class TestExtractCase:
    def test_extract_returns_none_on_empty_history(self):
        from kb.extractor import extract_case
        result = extract_case([])
        assert result is None

    def test_extract_calls_correct_provider(self):
        from kb.extractor import extract_case
        history = [
            {"role": "user", "content": "Pod OOMKilled 了"},
            {"role": "assistant", "content": "根因是内存限制过低，建议调高"},
        ] * 3

        mock_response = '{"has_conclusion": true, "symptom": "Pod OOMKilled", "root_cause": "内存限制低", "solution": "调高内存", "resource_kind": "Pod", "resource_name": "nginx", "namespace": "default"}'

        with patch("kb.extractor._call_anthropic", return_value=mock_response):
            with patch("config.settings.settings") as mock_settings:
                mock_settings.llm_provider = "anthropic"
                result = extract_case(history)

        assert result is not None
        assert result["symptom"] == "Pod OOMKilled"
        assert result["has_conclusion"] is True

    def test_extract_returns_none_when_no_conclusion(self):
        from kb.extractor import extract_case
        history = [{"role": "user", "content": "Pod 正常吗"}, {"role": "assistant", "content": "正常"}] * 3

        with patch("kb.extractor._call_anthropic", return_value='{"has_conclusion": false}'):
            with patch("config.settings.settings") as mock_settings:
                mock_settings.llm_provider = "anthropic"
                result = extract_case(history)

        assert result is None

    def test_extract_returns_none_on_llm_error(self):
        from kb.extractor import extract_case
        history = [{"role": "user", "content": "test"}, {"role": "assistant", "content": "ans"}] * 4

        with patch("kb.extractor._call_anthropic", side_effect=Exception("network error")):
            with patch("config.settings.settings") as mock_settings:
                mock_settings.llm_provider = "anthropic"
                result = extract_case(history)

        assert result is None
