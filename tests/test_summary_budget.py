"""③ 摘要生成的输入构成、预算闸门与模型层参数（纯内存，不触外部服务）

验证：
1. 父节点的请求输入是「自身正文 + 子节点摘要列表」，不再重送子树全文
2. 单次输入超过模型窗口预算时，节点内切块归并，任何一次调用的内容都在预算内
3. 父节点自身正文落盘，因此能进 ④ 的抽取批次
4. 本地 /api/generate 的参数走 options（顶层字段会被 Ollama 忽略）
5. 输出被 max_tokens 掐断时既留痕、也随返回值回调用方（缩批重发要能机器判定）
6. 上下文窗口探测能解析云端与本地两种响应，探不到时回落默认值
7. 输入预算的减数跟着调用方的输出额度走，改窗口后缓存的客户端会重建
"""
import asyncio
import json

import pytest

from content_extraction.document.models import ExtractedDocument, Section
from entity_extraction.document.chunker import iter_segments
from model_management import context_probe
from model_management import model_client as mc
from summary_generation.document import summarizer
from summary_generation.document.llm import count_tokens, load_prompt
from summary_generation.document.text_budget import (
    MIN_BUDGET_TOKENS,
    PROMPT_OVERHEAD_TOKENS,
    SUMMARY_OUTPUT_TOKENS,
    input_budget,
    split_to_budget,
    truncate_to_budget,
)
from utils.json_utils import extract_json

pytestmark = pytest.mark.unit

INPUT_MARK = "## 输入文本\n"
OUTPUT_MARK = "\n\n## 输出要求"


def prompt_content(prompt: str) -> str:
    """取节点摘要 prompt 里真正送进模型的那段内容"""
    if INPUT_MARK not in prompt:
        return prompt  # 文档描述等其他模板
    start = prompt.index(INPUT_MARK) + len(INPUT_MARK)
    end = prompt.index(OUTPUT_MARK)
    return prompt[start:end]


class Recorder:
    """替身 LLM：记录每次调用的 prompt，返回短摘要（绝不复述输入，否则降级会被误判成正常）"""

    def __init__(self):
        self.prompts = []

    async def __call__(self, model_config, prompt, max_tokens=None):
        self.prompts.append(prompt)
        return f"摘要{len(self.prompts)}"


def run_case(doc, context_length=1_000_000, threshold=200, with_description=False):
    rec = Recorder()
    original = summarizer.call_llm_async
    summarizer.call_llm_async = rec
    try:
        result = asyncio.run(summarizer._summarize(
            doc, summarizer.convert_sections(doc),
            {"model_name": "fake", "context_length": context_length},
            threshold, with_description))
    finally:
        summarizer.call_llm_async = original
    return rec, result


def make_doc():
    grand = Section(title="孙节", level=3, text="孙代正文" * 1200)
    child = Section(title="子节", level=2, text="子代正文" * 1200, children=[grand])
    # 父节点正文要够长，否则「自身正文 + 子摘要」不足阈值会直接跳过 LLM（那是另一条用例）
    parent = Section(title="父节", level=1, text="父节点自己的正文。" * 40, children=[child])
    return ExtractedDocument(doc_name="t.md", format="md", page_count=1, sections=[parent])


class TestParentInput:
    def test_parent_prompt_uses_child_summary_not_subtree_text(self):
        rec, _ = run_case(make_doc())
        assert len(rec.prompts) == 3  # 孙 → 子 → 父，自底向上
        parent_prompt = rec.prompts[-1]
        assert "父节点自己的正文。" in parent_prompt
        assert "【子节】" in parent_prompt          # 引用的是子节点摘要
        assert "子代正文" not in parent_prompt      # 不再重送子树全文
        assert "孙代正文" not in parent_prompt

    def test_levels_run_deepest_first(self):
        rec, _ = run_case(make_doc())
        assert "孙代正文" in rec.prompts[0]
        assert "子代正文" in rec.prompts[1]

    def test_short_text_skips_llm(self):
        doc = ExtractedDocument(
            doc_name="t.md", format="md", page_count=1,
            sections=[Section(title="短节", level=1, text="就一句话")])
        rec, result = run_case(doc)
        assert rec.prompts == []
        assert result["structure"][0]["summary"] == "就一句话"


class TestBudget:
    def test_budget_subtracts_output_and_overhead(self):
        budget = input_budget({"context_length": 100_000})
        assert budget == 100_000 - SUMMARY_OUTPUT_TOKENS - PROMPT_OVERHEAD_TOKENS

    def test_budget_follows_the_callers_output_reserve(self):
        """一次批量表格标注要返回整批结果，输出额度比节点摘要大得多

        减数还按 2048 算，派给模型的输入就会超出窗口；Ollama 固定 num_ctx 时掐的是
        输入尾部（后出现的表格先被吃掉），症状是标注缺失而不是报错。
        """
        reserve = 8192
        budget = input_budget({"context_length": 32768}, output_reserve=reserve)
        assert budget == 32768 - reserve - PROMPT_OVERHEAD_TOKENS
        assert budget < input_budget({"context_length": 32768})

    def test_reserve_larger_than_window_still_floors(self):
        assert input_budget({"context_length": 4096}, output_reserve=32768) == MIN_BUDGET_TOKENS

    def test_budget_falls_back_to_default_without_context_length(self):
        assert input_budget({}) > MIN_BUDGET_TOKENS
        assert input_budget({"context_length": 100}) == MIN_BUDGET_TOKENS

    def test_oversized_node_is_split_and_every_call_fits_budget(self):
        budget = input_budget({"context_length": 8192})
        rec, _ = run_case(make_doc(), context_length=8192)
        assert len(rec.prompts) > 3  # 切块归并带来的额外调用
        for prompt in rec.prompts:
            assert count_tokens(prompt_content(prompt)) <= budget

    def test_split_respects_budget_and_keeps_all_text(self):
        budget = 1500
        text = "句子内容。" * 2000
        parts = split_to_budget(text, budget)
        assert len(parts) > 1
        assert all(count_tokens(p) <= budget for p in parts)
        assert "".join(parts) == text

    def test_split_handles_text_without_sentence_marks(self):
        budget = 1200
        text = "a" * 9000  # 无句号无换行，仍必须切开
        parts = split_to_budget(text, budget)
        assert len(parts) > 1
        assert all(count_tokens(p) <= budget for p in parts)

    def test_text_within_budget_not_split(self):
        text = "很短的一段。"
        assert split_to_budget(text, 5000) == [text]

    def test_truncate_warns_instead_of_losing_content_silently(self, caplog):
        with caplog.at_level("WARNING"):
            out = truncate_to_budget("内容" * 5000, 1000)
        assert count_tokens(out) <= 1000
        assert "截断" in caplog.text

    def test_doc_description_falls_back_to_titles_when_skeleton_over_budget(self):
        rec = Recorder()
        original = summarizer.call_llm_async
        summarizer.call_llm_async = rec
        try:
            tree = summarizer.convert_sections(make_doc())
            for level in summarizer.flatten_by_depth(tree):
                for node in level:
                    node["summary"] = "摘要" * 3000
            asyncio.run(summarizer._generate_doc_description(tree,
                                                             {"context_length": 4096}))
        finally:
            summarizer.call_llm_async = original
        assert "summary" not in rec.prompts[0]  # 降级为只含标题的骨架


class TestEmittedContract:
    def test_parent_text_is_persisted_and_reaches_extraction_batches(self):
        _, result = run_case(make_doc())
        parent = result["structure"][0]
        assert parent["summary"]
        assert "prefix_summary" not in parent
        assert parent["text"].startswith("父节点自己的正文。")
        titles = [t for t, _ in iter_segments([parent], max_chunk=20000)]
        assert "父节" in titles  # ④ 现在能看到父节点正文

    def test_parent_and_leaf_share_the_summary_key(self):
        """下游（树导航 / 摘要检索 / Wiki / 前端）只读 summary，父节点另起 key 等于没人读"""
        _, result = run_case(make_doc())
        parent = result["structure"][0]
        leaf = parent["nodes"][0]["nodes"][0]
        assert {"summary", "text"} <= set(parent) and "nodes" in parent
        assert {"summary", "text"} <= set(leaf) and "nodes" not in leaf

    def test_leaf_contract_unchanged(self):
        _, result = run_case(make_doc())
        leaf = result["structure"][0]["nodes"][0]["nodes"][0]
        assert leaf["text"].startswith("孙代正文")
        assert leaf["summary"]


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class TestModelClientLocalParams:
    def test_generate_params_go_into_options(self, monkeypatch):
        captured = {}

        def fake_post(url, json=None, timeout=None):
            captured["url"] = url
            captured["body"] = json
            return _FakeResponse({"response": "结果", "done_reason": "stop", "eval_count": 2})

        monkeypatch.setattr(mc.requests, "post", fake_post)
        client = mc.ModelClient({"type": "local", "model_name": "m", "api_url": "http://h",
                                 "context_length": 131072})
        assert client.call_text("提示词", temperature=0.3, max_tokens=2048) == "结果"
        options = captured["body"]["options"]
        assert options["num_predict"] == 2048
        assert options["temperature"] == 0.3
        assert options["num_ctx"] == 131072
        assert "max_tokens" not in captured["body"]  # 顶层字段 Ollama 不认

    def test_text_call_does_not_force_json_on_local_model(self, monkeypatch):
        """摘要是白话，本地模型被套上 format=json 会把引号和花括号一起写进库"""
        captured = {}

        def fake_post(url, json=None, timeout=None):
            captured["body"] = json
            return _FakeResponse({"response": "一段摘要", "done_reason": "stop", "eval_count": 4})

        monkeypatch.setattr(mc.requests, "post", fake_post)
        mc.ModelClient({"type": "local", "model_name": "m", "api_url": "http://h"}).call_text("提示词")
        assert captured["body"]["format"] == "text"

    def test_json_call_keeps_local_format_constraint(self, monkeypatch):
        captured = {}

        def fake_post(url, json=None, timeout=None):
            captured["body"] = json
            return _FakeResponse({"response": '{"a": 1}', "done_reason": "stop", "eval_count": 4})

        monkeypatch.setattr(mc.requests, "post", fake_post)
        got = mc.ModelClient({"type": "local", "model_name": "m",
                             "api_url": "http://h"}).call_json("提示词")
        assert got == {"a": 1}
        assert captured["body"]["format"] == "json"

    def test_connection_probe_does_not_warn_about_truncation(self, monkeypatch, caplog):
        """连通性探测只给 10 token 输出，被掐断属预期，不该刷告警"""
        monkeypatch.setattr(mc.requests, "post",
                            lambda url, json=None, timeout=None: _FakeResponse(
                                {"response": "hi", "done_reason": "length", "eval_count": 10}))
        with caplog.at_level("WARNING"):
            ok = mc.ModelClient({"type": "local", "model_name": "m",
                                 "api_url": "http://h"}).test_connection()
        assert ok is True
        assert "截断" not in caplog.text

    def test_local_length_truncation_is_warned(self, monkeypatch, caplog):
        monkeypatch.setattr(mc.requests, "post",
                            lambda url, json=None, timeout=None: _FakeResponse(
                                {"response": "半截", "done_reason": "length", "eval_count": 8192}))
        with caplog.at_level("WARNING"):
            mc.ModelClient({"type": "local", "model_name": "m", "api_url": "http://h"}
                           ).call_text("提示词", max_tokens=8192)
        assert "截断" in caplog.text

    def test_cloud_length_truncation_is_warned(self, monkeypatch, caplog):
        def fake_post(url, json=None, headers=None, timeout=None):
            return _FakeResponse({"choices": [{"message": {"content": "半截"},
                                               "finish_reason": "length"}],
                                  "usage": {"completion_tokens": 8192}})

        monkeypatch.setattr(mc.requests, "post", fake_post)
        with caplog.at_level("WARNING"):
            mc.ModelClient({"type": "cloud", "model_name": "m", "api_url": "http://h",
                            "api_key": "k"}).call_text("提示词", max_tokens=8192)
        assert "截断" in caplog.text

    def test_context_length_defaults_when_record_never_probed(self):
        config = mc.ModelConfig.from_dict({"type": "local", "model_name": "m"})
        assert config.context_length == mc.DEFAULT_CONTEXT_LENGTH
        assert config.to_dict()["context_length"] == mc.DEFAULT_CONTEXT_LENGTH


class TestTruncationSignal:
    """缩批重发要能机器判定：截断标志必须随返回值走

    记在实例属性上会串台 —— get_model_client() 是跨线程共享的缓存单例，摘要与批量
    抽取又用 asyncio.gather 并发。
    """

    def _local(self):
        return mc.ModelClient({"type": "local", "model_name": "m", "api_url": "http://h"})

    def test_truncated_json_reports_both_signals(self, monkeypatch):
        monkeypatch.setattr(mc.requests, "post",
                            lambda url, json=None, timeout=None: _FakeResponse(
                                {"response": '{"sheets": [{"n"', "done_reason": "length",
                                 "eval_count": 8192}))
        data, truncated = self._local().call_json_ex("提示词", max_tokens=8192)
        assert truncated is True
        # 修复链可能救回一个空壳（如 {"sheets": []}），但绝不允许披上抽取结果的形态
        assert not (isinstance(data, dict) and "entities" in data)

    def test_garbage_output_is_not_reported_as_truncation(self, monkeypatch):
        """没截断却解析失败 = 模型吐了不合格式的文本，加额度或拆批都没用，只能降级"""
        monkeypatch.setattr(mc.requests, "post",
                            lambda url, json=None, timeout=None: _FakeResponse(
                                {"response": "抱歉，我无法完成", "done_reason": "stop",
                                 "eval_count": 8}))
        data, truncated = self._local().call_json_ex("提示词", max_tokens=8192)
        assert data is None
        assert truncated is False

    def test_cloud_truncation_signal_comes_from_finish_reason(self, monkeypatch):
        half_json = '{"sheets": [{"title": "一季度'

        def fake_post(url, json=None, headers=None, timeout=None):
            return _FakeResponse({"choices": [{"message": {"content": half_json},
                                               "finish_reason": "length"}],
                                  "usage": {"completion_tokens": 8192}})

        monkeypatch.setattr(mc.requests, "post", fake_post)
        client = mc.ModelClient({"type": "cloud", "model_name": "m", "api_url": "http://h",
                                 "api_key": "k"})
        _, truncated = client.call_json_ex("提示词", max_tokens=8192)
        assert truncated is True

    def test_flag_is_not_kept_on_the_instance(self, monkeypatch):
        replies = iter([
            {"response": "半截", "done_reason": "length", "eval_count": 8192},
            {"response": '{"a": 1}', "done_reason": "stop", "eval_count": 5},
        ])
        monkeypatch.setattr(mc.requests, "post",
                            lambda url, json=None, timeout=None: _FakeResponse(next(replies)))
        client = self._local()
        assert client.call_json_ex("提示词")[1] is True
        assert client.call_json_ex("提示词") == ({"a": 1}, False)
        assert not [k for k in vars(client) if "trunc" in k]


class TestCloudTransport:
    """云端两条路径共用一个 HTTP 出口：鉴权头与响应形状判定只允许有一处"""

    def _cloud(self):
        return mc.ModelClient({"type": "cloud", "model_name": "m",
                               "api_url": "http://h/v1", "api_key": "sk-test",
                               "max_retries": 1})

    def test_both_paths_post_to_the_same_endpoint_with_the_same_header(self, monkeypatch):
        seen = []

        def fake_post(url, json=None, headers=None, timeout=None):
            seen.append((url, headers))
            return _FakeResponse({"choices": [{"message": {"content": "好的"},
                                               "finish_reason": "stop"}],
                                  "usage": {"completion_tokens": 2}})

        monkeypatch.setattr(mc.requests, "post", fake_post)
        client = self._cloud()
        client.call_text("提示词")
        client.call_with_tools([{"role": "user", "content": "查一下"}], [])

        assert len(seen) == 2
        assert {url for url, _ in seen} == {"http://h/v1/chat/completions"}
        assert all(h["Authorization"] == "Bearer sk-test" for _, h in seen)

    def test_200_without_choices_fails_with_response_context_not_keyerror(self,
                                                                          monkeypatch,
                                                                          caplog):
        """网关把错误吞成 200（body 没有 choices）时，日志要能看出是哪一步、回了什么"""
        monkeypatch.setattr(mc.requests, "post",
                            lambda url, json=None, headers=None, timeout=None:
                            _FakeResponse({"error": "upstream"}))
        with caplog.at_level("WARNING"):
            json_reply = self._cloud().call_json_ex("提示词")
            tool_reply = self._cloud().call_with_tools(
                [{"role": "user", "content": "x"}], [])

        assert json_reply == (None, False)
        assert tool_reply is None
        assert "没有 choices" in caplog.text
        assert "KeyError" not in caplog.text


class TestJsonRepairScope:
    """精准修复只认实体/关系形态：否则半截的表格 JSON 会被"修"成抽取空结果"""

    def test_non_extraction_json_keeps_its_own_shape(self):
        got = extract_json('{"sheets": [{"n')
        assert not (isinstance(got, dict) and set(got) == {"entities", "relationships"})

    def test_extraction_payload_still_salvages_complete_objects(self):
        raw = ('{"entities": [{"name": "张三", "type": "person"}, {"name": "李四", "type": "person"}, '
               '{"name": "王')
        got = extract_json(raw)
        assert got is not None
        assert [e["name"] for e in got["entities"]] == ["张三", "李四"]


class TestModelClientCache:
    def test_context_length_change_rebuilds_cached_client(self, temp_db, monkeypatch):
        """探测/手填改完窗口后必须换实例，否则 num_ctx 与输入预算还按旧值跑"""
        import config.database
        from model_management.model_service import ModelService

        monkeypatch.setattr(config.database, "SessionLocal", temp_db)
        current = {"type": "local", "model_name": "m", "api_url": "http://h",
                   "context_length": 32768}
        # 每次返回新字典：签名比对看的是内容，不能因为换了个对象就误判成"配置变了"
        monkeypatch.setattr(ModelService, "get_available_model", lambda db: dict(current))
        monkeypatch.setattr(mc, "_client_cache", None)
        monkeypatch.setattr(mc, "_client_cache_sig", ())

        first = mc.get_model_client()
        assert first is mc.get_model_client()  # 配置没变就复用
        current["context_length"] = 131072
        second = mc.get_model_client()
        assert second is not first
        assert second.config.context_length == 131072


class TestContextProbe:
    def test_cloud_reads_context_length_of_the_named_model(self, monkeypatch):
        monkeypatch.setattr(mc.requests, "get", lambda url, headers=None, timeout=None:
                            _FakeResponse({"data": [
                                {"id": "other", "context_length": 8192},
                                {"id": "mine", "context_length": 1_000_000},
                            ]}))
        got = context_probe.probe_context_length(
            {"type": "cloud", "api_url": "http://h/v1", "api_key": "k", "model_name": "mine"})
        assert got == 1_000_000

    def test_cloud_ignores_other_models_when_named_model_absent(self, monkeypatch):
        monkeypatch.setattr(mc.requests, "get", lambda url, headers=None, timeout=None:
                            _FakeResponse({"data": [{"id": "other", "context_length": 8192}]}))
        assert context_probe.probe_context_length(
            {"type": "cloud", "api_url": "http://h/v1", "model_name": "mine"}) is None

    def test_local_reads_gguf_context_length(self, monkeypatch):
        monkeypatch.setattr(mc.requests, "post", lambda url, json=None, timeout=None:
                            _FakeResponse({"model_info": {"qwen2.context_length": 262144}}))
        assert context_probe.probe_context_length(
            {"type": "local", "api_url": "http://h", "model_name": "m"}) == 262144

    def test_local_falls_back_to_num_ctx_parameter(self, monkeypatch):
        monkeypatch.setattr(mc.requests, "post", lambda url, json=None, timeout=None:
                            _FakeResponse({"parameters": "num_ctx    4096\ntemperature 0"}))
        assert context_probe.probe_context_length(
            {"type": "local", "api_url": "http://h", "model_name": "m"}) == 4096

    def test_probe_failure_returns_none_not_raise(self, monkeypatch):
        def boom(*args, **kwargs):
            raise mc.requests.exceptions.ConnectionError("网络不可达")

        monkeypatch.setattr(mc.requests, "get", boom)
        monkeypatch.setattr(mc.requests, "post", boom)
        assert context_probe.probe_context_length(
            {"type": "cloud", "api_url": "http://h/v1", "model_name": "m"}) is None
        assert context_probe.probe_context_length(
            {"type": "local", "api_url": "http://h", "model_name": "m"}) is None

    def test_missing_api_url_returns_none(self):
        assert context_probe.probe_context_length({"type": "cloud", "api_url": ""}) is None


class TestPromptTemplates:
    """模板只存 prompts/*.md 一份：缺文件在导入期就抛错，不再走代码内兜底副本"""

    def test_templates_are_the_md_files(self):
        for name, loaded in (("prompt_summary_node.md", summarizer._NODE_SUMMARY_PROMPT),
                             ("prompt_doc_description.md", summarizer._DOC_DESCRIPTION_PROMPT),
                             ("prompt_table_node.md", summarizer._TABLE_NODE_PROMPT)):
            assert load_prompt(name) == loaded

    def test_missing_template_raises(self):
        with pytest.raises(FileNotFoundError):
            load_prompt("prompt_does_not_exist.md")

    def test_table_template_carries_property_vocabulary_slot(self):
        """反例守卫：旧的代码内兜底副本缺 {property_types}，属性词表注入会静默变空操作"""
        assert "{property_types}" in summarizer._TABLE_NODE_PROMPT
