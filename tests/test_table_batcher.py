"""③ 表格分支单测 —— 装批两侧预算、JSON 契约解析、四条降级留痕（替身 LLM，无需模型）

覆盖 docs/data-flow.md「表格文件分支」③ 一节的判据：
1. 30 sheet + 小窗口 → 无 sheet 被拆到两批、每批输入 ≤ budget_in、每批输出估算 ≤ budget_out
2. budget_in 的减数是 TABLE_OUTPUT_TOKENS 而不是 SUMMARY_OUTPUT_TOKENS
3. 不平衡 JSON → 判截断（拆批重试 / 留痕），不是静默空标注
"""
import json
from dataclasses import asdict
from typing import Any, Dict, List

import pytest

from content_extraction.document.models import ExtractedDocument, KIND_PROSE, KIND_TABLE, Section
from content_extraction.document.table_model import (
    MAX_PROFILE_COLUMNS,
    PREVIEW_ROWS,
    SheetTable,
    render_profile,
)
from summary_generation.document import summarizer
from summary_generation.document.summarizer import (
    _clean_columns,
    _clean_rels,
    summarize_document,
)
from summary_generation.document.table_batcher import (
    INPUT_SAFETY,
    OUTPUT_PER_COLUMN,
    OUTPUT_PER_SHEET,
    PROMPT_OVERHEAD_TOKENS,
    TABLE_OUTPUT_TOKENS,
    TableUnit,
    batch_text,
    estimate_output_tokens,
    pack_batches,
    table_budget,
)
from summary_generation.document.text_budget import SUMMARY_OUTPUT_TOKENS

pytestmark = pytest.mark.unit


def sheet(title: str, columns: List[str], rows: int = 3) -> SheetTable:
    return SheetTable(
        title=title,
        columns=columns,
        column_types=["TEXT"] * len(columns),
        row_count=rows,
        samples=[columns, [f"{c}值" for c in columns]][:PREVIEW_ROWS] if rows else [],
    )


def shape(title: str, columns: List[str], rows: int = 3) -> Dict[str, Any]:
    return asdict(sheet(title, columns, rows))


def document(tables: List[SheetTable], doc_name: str = "销售统计.xlsx") -> ExtractedDocument:
    return ExtractedDocument(
        doc_name=doc_name, format="xlsx",
        sections=[Section(title=t.title, level=1, text=render_profile(t), kind=KIND_TABLE)
                  for t in tables],
        meta={"skipped_sheets": [], "sheets": [asdict(t) for t in tables]},
    )


class TestBudget:
    def test_budget_in_subtracts_table_output(self):
        """决策 13 的防线：输入预算的减数是表格输出额度，沿用 2048 会把尾部 sheet 挤没"""
        context = 32768
        budget_in, budget_out = table_budget({"context_length": context})
        assert budget_in == int((context - TABLE_OUTPUT_TOKENS - PROMPT_OVERHEAD_TOKENS) * INPUT_SAFETY)
        assert budget_out == TABLE_OUTPUT_TOKENS - PROMPT_OVERHEAD_TOKENS
        # 若错用 SUMMARY_OUTPUT_TOKENS 做减数，预算会大出一截
        assert budget_in < int((context - SUMMARY_OUTPUT_TOKENS - PROMPT_OVERHEAD_TOKENS) * INPUT_SAFETY)

    def test_tiny_window_budget_floors_at_min(self):
        budget_in, budget_out = table_budget({"context_length": 4096})
        assert budget_in >= 256 and budget_out >= 256


class TestPacking:
    def test_no_sheet_split_across_batches(self):
        tables = [sheet(f"表{i}", [f"列{j}" for j in range(6)]) for i in range(30)]
        shapes = [asdict(t) for t in tables]
        batches, (budget_in, budget_out) = pack_batches(shapes, {"context_length": 8192})
        titles = [unit.title for batch in batches for unit in batch]
        assert sorted(titles) == sorted(t.title for t in tables)
        assert len(set(titles)) == len(titles)
        from summary_generation.document.llm import count_tokens
        for batch in batches:
            assert sum(count_tokens(unit.text) for unit in batch) <= budget_in
            assert estimate_output_tokens(batch) <= budget_out
        assert len(batches) > 1  # 小窗口下确实分了批

    def test_output_budget_limits_batch_size(self):
        """列数多的 sheet 先撞输出预算（输入侧 128k 窗口根本装得下）"""
        from summary_generation.document.llm import count_tokens

        wide = [sheet(f"表{i}", [f"列{c}" for c in range(MAX_PROFILE_COLUMNS)])
                for i in range(10)]
        shapes = [asdict(t) for t in wide]
        batches, (budget_in, budget_out) = pack_batches(shapes, {"context_length": 128000})
        assert len(batches) < len(wide)
        for batch in batches:
            assert estimate_output_tokens(batch) <= budget_out
            assert sum(count_tokens(unit.text) for unit in batch) < budget_in

    def test_oversized_single_sheet_is_shrunk_not_split(self):
        columns = [f"这是一个非常长的中文列名用来撑大表档案{i}" for i in range(30)]
        units, (budget_in, _) = pack_batches([shape("宽表", columns)], {"context_length": 4096})
        unit = units[0][0]
        from summary_generation.document.llm import count_tokens
        assert count_tokens(unit.text) <= budget_in
        assert unit.shrink  # 压预算的痕迹要落进 table_meta
        assert len(unit.columns) <= len(columns)

    def test_batch_text_keeps_every_sheet_profile(self):
        units = [[TableUnit(title="甲", text="【工作表】甲", columns=["a"], row_count=1,
                            col_count=1),
                  TableUnit(title="乙", text="【工作表】乙", columns=["b"], row_count=1,
                            col_count=1)]]
        text = batch_text(units[0])
        assert "【工作表】甲" in text and "【工作表】乙" in text


def annotation(title: str, columns: List[str], primary: str = "",
               rels: List[Dict[str, str]] = None) -> Dict[str, Any]:
    return {
        "title": title,
        "summary": f"{title}的业务摘要",
        "columns": [
            ({"n": name, "r": "entity", "t": "organization", "d": f"{name}的含义"}
             if name == primary or (rels and any(name in (r["s"], r["o"]) for r in rels))
             else {"n": name, "r": "attribute", "d": f"{name}的值"})
            for name in columns
        ],
        "rels": rels or [],
        "primary": primary,
    }


def responder(by_prompt):
    """替身 LLM：按 prompt 里表档案的个数决定返回什么（拆批重试后条数会变）"""
    calls: List[Dict[str, Any]] = []

    async def _call(model_config, prompt, max_tokens):
        calls.append({"prompt": prompt, "max_tokens": max_tokens})
        return by_prompt(prompt, len(calls))

    return _call, calls


class TestReplyClassification:
    """截断与垃圾输出是两条成因，留痕必须分开（拆批有用 vs 只能降级）"""

    def test_truncation_signal_wins_over_parsed_content(self):
        data, reason = summarizer._classify_reply({"sheets": []}, True)
        assert data is None and reason == "table_annotation_truncated"

    def test_unparsable_is_invalid_not_truncated(self):
        for payload in (None, [], "字符串", 7):
            data, reason = summarizer._classify_reply(payload, False)
            assert data is None and reason == "table_annotation_invalid", payload

    def test_object_without_truncation_is_usable(self):
        data, reason = summarizer._classify_reply({"sheets": []}, False)
        assert reason is None and data == {"sheets": []}


def unit_of(title: str, columns: List[str]) -> TableUnit:
    return TableUnit(title=title, text=f"【工作表】{title}", columns=columns,
                     row_count=5, col_count=len(columns))


class TestColumnClosure:
    def test_missing_columns_filled_as_none_when_ratio_is_low(self):
        columns, reason = _clean_columns(
            {"columns": [{"n": "部门", "r": "entity", "t": "organization", "d": "销售部门"},
                         {"n": "销售额", "r": "attribute", "d": "当月销售额"},
                         {"n": "月份", "r": "entity", "t": "concept", "d": "统计月份"},
                         {"n": "编号", "r": "none", "d": "流水号"}],
             "primary": "部门"},
            unit_of("月度汇总", ["部门", "销售额", "月份", "编号", "备注"]))
        assert reason is None
        assert [c["n"] for c in columns] == ["部门", "销售额", "月份", "编号", "备注"]
        assert columns[-1]["r"] == "none" and columns[-1]["d"] == ""
        assert columns[0]["primary"] is True

    def test_high_missing_ratio_fails_the_annotation(self):
        columns, reason = _clean_columns(
            {"columns": [{"n": "部门", "r": "entity", "t": "organization"}]},
            unit_of("月度汇总", ["部门", "销售额", "备注", "月份"]))
        assert columns is None and reason == "table_columns_missing"

    def test_primary_must_be_an_entity_column(self):
        """声明的主列不是 entity 列：唯一 entity 列顶上，多个则不猜"""
        columns, _ = _clean_columns(
            {"columns": [{"n": "部门", "r": "attribute", "d": "x"},
                         {"n": "省份", "r": "entity", "t": "location", "d": "y"}],
             "primary": "部门"},
            unit_of("表", ["部门", "省份"]))
        assert columns[0]["primary"] is False
        assert columns[1]["primary"] is True

        columns, _ = _clean_columns(
            {"columns": [{"n": "部门", "r": "entity", "t": "organization", "d": "x"},
                         {"n": "省份", "r": "entity", "t": "location", "d": "y"},
                         {"n": "销售额", "r": "attribute", "d": "z"}],
             "primary": "销售额"},
            unit_of("表", ["部门", "省份", "销售额"]))
        assert [item["primary"] for item in columns] == [False, False, False]

    def test_hallucinated_column_names_are_dropped(self):
        columns, _ = _clean_columns(
            {"columns": [{"n": "部门", "r": "entity", "t": "organization", "d": "x"},
                         {"n": "不存在的列", "r": "entity", "t": "concept", "d": "y"}],
             "primary": "部门"},
            unit_of("表", ["部门"]))
        assert [c["n"] for c in columns] == ["部门"]

    def test_rels_need_both_endpoints_as_entity(self):
        rels = _clean_rels(
            {"rels": [{"s": "部门", "p": "属于", "o": "省份"},
                      {"s": "部门", "p": "属于", "o": "销售额"},
                      {"s": "部门", "p": "", "o": "月份"},
                      {"s": "部门", "p": "属于", "o": "省份"}]},
            ["部门", "省份", "月份"])
        assert rels == [{"s": "部门", "p": "属于", "o": "省份"}]


class TestTableDispatch:
    def _run(self, tables, by_prompt, context=32768):
        fake, calls = responder(by_prompt)
        original = summarizer.call_llm_json_async
        summarizer.call_llm_json_async = fake
        try:
            result = summarize_document(document(tables),
                                        model_config={"context_length": context},
                                        generate_doc_description=False)
        finally:
            summarizer.call_llm_json_async = original
        return result, calls

    def test_happy_path_persists_columns_and_meta(self):
        tables = [sheet("月度汇总", ["部门", "省份", "销售额"])]
        good = ({"sheets": [annotation("月度汇总", ["部门", "省份", "销售额"],
                                       primary="部门",
                                       rels=[{"s": "部门", "p": "属于", "o": "省份"}])]}, False)
        result, calls = self._run(tables, lambda prompt, index: good)

        assert calls[0]["max_tokens"] == TABLE_OUTPUT_TOKENS
        assert result["kind"] == KIND_TABLE          # 文档级声明由节级 kind 聚合而来
        leaf = result["structure"][0]
        assert leaf["kind"] == KIND_TABLE
        assert leaf["title"] == "月度汇总"
        assert leaf["summary"] == "月度汇总的业务摘要"
        assert leaf["text"].startswith("【工作表】月度汇总")
        assert [c["n"] for c in leaf["table_columns"]] == ["部门", "省份", "销售额"]
        assert leaf["table_meta"] == {"row_count": 3, "col_count": 3,
                                      "rels": [{"s": "部门", "p": "属于", "o": "省份"}],
                                      "skipped_reason": None}
        assert result["table_report"]["invalid"] == []
        json.dumps(result, ensure_ascii=False)  # 落盘契约：全部可序列化

    def test_truncated_output_retries_with_smaller_batches(self):
        tables = [sheet("甲", ["a1", "a2"]), sheet("乙", ["b1", "b2"])]

        def respond(prompt, index):
            if "【工作表】甲" in prompt and "【工作表】乙" in prompt:   # 整批：输出被额度掐断
                return None, True
            title = "甲" if "【工作表】甲" in prompt else "乙"
            columns = ["a1", "a2"] if title == "甲" else ["b1", "b2"]
            return {"sheets": [annotation(title, columns, primary=columns[0])]}, False

        result, calls = self._run(tables, respond)
        assert len(calls) == 3                        # 1 次整批 + 2 次半批
        assert result["table_report"]["split_retry"] == ["甲", "乙"]
        assert [leaf["title"] for leaf in result["structure"]] == ["甲", "乙"]
        assert all(leaf["table_columns"] for leaf in result["structure"])
        assert result["table_report"]["truncated"] == []

    def test_truncated_twice_degrades_without_silent_empty(self):
        tables = [sheet("甲", ["a1", "a2"]), sheet("乙", ["b1", "b2"])]

        result, calls = self._run(tables, lambda prompt, index: (None, True))
        assert len(calls) == 3                        # 拆批重试过，仍然截断
        assert result["table_report"]["truncated"] == ["甲", "乙"]
        for leaf in result["structure"]:
            assert leaf["table_columns"] == []
            assert leaf["summary"] == leaf["text"]    # 摘要回退表档案，标注不猜

    def test_garbage_output_marks_invalid(self):
        tables = [sheet("甲", ["a1", "a2"])]
        result, calls = self._run(tables, lambda prompt, index: (None, False))
        assert len(calls) == 1                        # 没截断，不白跑一次拆批
        assert result["table_report"]["invalid"] == ["甲"]
        assert result["structure"][0]["table_columns"] == []

    def test_unmatched_sheet_title_is_not_fuzzy_matched(self):
        tables = [sheet("月度汇总", ["部门", "销售额"])]
        wrong = {"sheets": [annotation("月度汇总表", ["部门", "销售额"], primary="部门")]}
        result, _ = self._run(tables, lambda prompt, index: (wrong, False))
        assert result["table_report"]["unmatched"] == ["月度汇总"]
        assert result["structure"][0]["table_columns"] == []
        assert result["structure"][0]["summary"] == result["structure"][0]["text"]

    def test_columns_missing_beyond_ratio_marks_the_sheet(self):
        tables = [sheet("月度汇总", ["部门", "省份", "销售额", "月份"])]
        partial = {"sheets": [annotation("月度汇总", ["部门"], primary="部门")]}
        result, _ = self._run(tables, lambda prompt, index: (partial, False))
        assert result["table_report"]["columns_missing"] == ["月度汇总"]
        assert result["structure"][0]["table_columns"] == []

    def test_llm_exception_degrades_to_profile_text(self):
        tables = [sheet("甲", ["a1", "a2"])]

        async def boom(model_config, prompt, max_tokens):
            raise RuntimeError("连接被拒绝")

        original = summarizer.call_llm_json_async
        summarizer.call_llm_json_async = boom
        try:
            result = summarize_document(document(tables),
                                        model_config={"context_length": 32768},
                                        generate_doc_description=False)
        finally:
            summarizer.call_llm_json_async = original
        assert result["table_report"]["invalid"] == ["甲"]
        assert result["structure"][0]["table_meta"]["row_count"] == 3

    def test_prose_document_untouched_by_dispatch(self):
        """② 没声明表格的文档走章节树调度，不碰表格分支"""
        extracted = ExtractedDocument(
            doc_name="方案.docx", format="docx",
            sections=[Section(title="第一章", level=1, text="正文" * 300)])
        called = {}

        async def fake(model_config, prompt, max_tokens=None):
            called["prompt"] = prompt
            return "第一章摘要"

        original = summarizer.call_llm_async
        summarizer.call_llm_async = fake
        try:
            result = summarize_document(extracted, model_config={"context_length": 32768},
                                        generate_doc_description=False)
        finally:
            summarizer.call_llm_async = original
        assert "table_report" not in result
        assert result["kind"] == KIND_PROSE
        assert result["structure"][0]["kind"] == KIND_PROSE
        assert result["structure"][0]["summary"] == "第一章摘要"

    def test_extension_is_not_the_dispatch_key(self):
        """分派只看 Section.kind：.xlsx 但 ② 按正文抽取的文档不会误入表格分支"""
        extracted = ExtractedDocument(
            doc_name="说明.xlsx", format="xlsx",
            sections=[Section(title="说明", level=1, text="正文" * 300)])
        hits = {"json": 0, "text": 0}

        async def fake_json(model_config, prompt, max_tokens=None):
            hits["json"] += 1
            raise AssertionError("表格分支不该被调用")

        async def fake_text(model_config, prompt, max_tokens=None):
            hits["text"] += 1
            return "说明摘要"

        original_json = summarizer.call_llm_json_async
        original_text = summarizer.call_llm_async
        summarizer.call_llm_json_async = fake_json
        summarizer.call_llm_async = fake_text
        try:
            result = summarize_document(extracted, model_config={"context_length": 32768},
                                        generate_doc_description=False)
        finally:
            summarizer.call_llm_json_async = original_json
            summarizer.call_llm_async = original_text
        assert hits == {"json": 0, "text": 1}
        assert result["kind"] == KIND_PROSE

    def test_kind_dispatches_even_without_table_extension(self):
        """反向：② 声明 kind=table 就进表格调度，扩展名不参与判定"""
        tables = [sheet("月度汇总", ["部门", "销售额"])]
        extracted = ExtractedDocument(
            doc_name="销售统计.md", format="md",
            sections=[Section(title=t.title, level=1, text=render_profile(t),
                              kind=KIND_TABLE) for t in tables],
            meta={"skipped_sheets": [], "sheets": [asdict(t) for t in tables]})
        good = ({"sheets": [annotation("月度汇总", ["部门", "销售额"], primary="部门")]}, False)

        async def fake_json(model_config, prompt, max_tokens=None):
            return good

        original = summarizer.call_llm_json_async
        summarizer.call_llm_json_async = fake_json
        try:
            result = summarize_document(extracted, model_config={"context_length": 32768},
                                        generate_doc_description=False)
        finally:
            summarizer.call_llm_json_async = original
        assert "table_report" in result
        assert result["kind"] == KIND_TABLE

    def test_empty_section_tree_is_not_a_table_document(self):
        """空章节树不能因 all([]) 为真而误入表格分支"""
        from summary_generation.document.tree_utils import convert_sections, is_table_tree

        extracted = ExtractedDocument(doc_name="空.pdf", format="pdf", sections=[])
        assert convert_sections(extracted) == []
        assert is_table_tree([]) is False
        assert is_table_tree(convert_sections(document([sheet("甲", ["a"])]))) is True
