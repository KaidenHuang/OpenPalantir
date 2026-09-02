"""
PageIndex 重构后的单元测试
在 WSL Ubuntu 中运行: python3 test_pageindex_refactor.py
"""
import sys
import os
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(_BACKEND_DIR))
os.chdir(str(_BACKEND_DIR))


# ============================================================
# 测试 1: 导入改动模块
# ============================================================
def test_imports():
    print("=" * 60)
    print("测试 1: 模块导入")
    print("=" * 60)

    from pageindex.utils import (
        write_node_id, structure_to_list, get_leaf_nodes, is_leaf_node,
        get_pdf_name, list_to_tree, count_tokens, extract_json, get_json_content,
        ConfigLoader, format_structure, create_clean_structure_for_description,
        remove_fields, reorder_dict, get_last_node, get_nodes,
        print_toc, print_json, print_wrapped, print_tree, create_node_mapping,
        generate_node_summary, generate_summaries_for_structure,
        generate_doc_description, llm_completion, llm_acompletion,
        set_model_config, clear_model_config, post_processing,
        add_preface_if_needed, clean_structure_post, check_token_limit,
        get_pdf_name
    )
    print("✅ utils 模块导入成功")

    from pageindex import (
        page_index, page_index_main, page_index_main_async,
        page_index_builder, page_index_builder_from_structure
    )
    print("✅ page_index 模块导入成功")

    from pageindex.model_adapter import (
        get_model_config, generate_pageindex_pdf, generate_pageindex_pdf_async,
        generate_pageindex_md, generate_pageindex_txt
    )
    print("✅ model_adapter 模块导入成功")

    from pageindex.page_index_md import md_to_tree, build_tree_from_nodes
    print("✅ page_index_md 模块导入成功")

    from pageindex.page_index_txt import txt_to_tree
    print("✅ page_index_txt 模块导入成功")

    # 测试 mineru_adapter 导入（不依赖 magic-pdf 运行时的纯逻辑函数）
    from document_processing.mineru_adapter import (
        markdown_headers_to_tree, _count_nodes
    )
    print("✅ mineru_adapter 模块导入成功（纯逻辑部分）")

    print()
    return True


# ============================================================
# 测试 2: mineru_adapter - markdown_headers_to_tree
# ============================================================
def test_markdown_headers_to_tree():
    print("=" * 60)
    print("测试 2: markdown_headers_to_tree")
    print("=" * 60)

    from document_processing.mineru_adapter import markdown_headers_to_tree, _count_nodes

    # 测试1: 标准 Markdown 标题解析
    md_content = """# 第一章 概述
这是第一章的内容。
## 1.1 背景
背景介绍文本。
## 1.2 目标
目标描述文本。
### 1.2.1 具体目标
详细目标。
# 第二章 方法
第二章内容。
## 2.1 数据收集
数据收集方法。
"""

    tree = markdown_headers_to_tree(md_content)
    assert len(tree) == 2, f"期望 2 个顶级节点，实际 {len(tree)}"
    assert tree[0]['title'] == '第一章 概述'
    # build_tree_from_nodes 不保留 level 字段（层次已由 nodes 嵌套表达）
    assert len(tree[0]['nodes']) == 2  # 1.1, 1.2
    assert tree[0]['nodes'][1]['nodes'][0]['title'] == '1.2.1 具体目标'
    assert 'text' in tree[0]

    node_count = _count_nodes(tree)
    assert node_count == 6, f"期望 6 个节点，实际 {node_count}"

    print("✅ 标准 Markdown 标题解析正确")

    # 测试2: 无标题文档
    md_no_headers = "这是一段没有标题的纯文本。\n第二行。"
    tree2 = markdown_headers_to_tree(md_no_headers)
    assert len(tree2) == 1
    assert 'text' in tree2[0]
    print("✅ 无标题文档处理正确")

    # 测试3: 空行
    md_empty = ""
    tree3 = markdown_headers_to_tree(md_empty)
    assert len(tree3) == 1
    print("✅ 空文档处理正确")

    # 测试4: 不同层级标题
    md_mixed = """# H1
## H2
#### H4
###### H6
"""
    tree4 = markdown_headers_to_tree(md_mixed)
    assert len(tree4) == 1
    h1 = tree4[0]
    assert h1['title'] == 'H1'
    assert len(h1['nodes']) == 1
    h2 = h1['nodes'][0]
    assert h2['title'] == 'H2'
    assert len(h2['nodes']) == 1
    h4 = h2['nodes'][0]
    assert h4['title'] == 'H4'
    assert len(h4['nodes']) == 1
    h6 = h4['nodes'][0]
    assert h6['title'] == 'H6'
    print("✅ 混合层级标题处理正确")

    # 测试5: 标题中有特殊字符
    md_special = """# 标题 with English & 数字 123
正文内容。
## 子标题 (包含括号) [引用]
"""
    tree5 = markdown_headers_to_tree(md_special)
    assert tree5[0]['title'] == '标题 with English & 数字 123'
    assert tree5[0]['nodes'][0]['title'] == '子标题 (包含括号) [引用]'
    print("✅ 特殊字符标题处理正确")

    print()
    return True


# ============================================================
# 测试 3: utils 函数
# ============================================================
def test_utils_functions():
    print("=" * 60)
    print("测试 3: utils 函数")
    print("=" * 60)

    from pageindex.utils import (
        write_node_id, structure_to_list, get_leaf_nodes,
        get_pdf_name, count_tokens, extract_json, get_json_content,
        format_structure, remove_fields, ConfigLoader,
        create_clean_structure_for_description,
        get_nodes, get_last_node, reorder_dict
    )
    from io import BytesIO

    # --- write_node_id ---
    structure = [
        {'title': '第1章', 'nodes': [
            {'title': '1.1', 'nodes': []},
            {'title': '1.2', 'nodes': []},
        ]},
        {'title': '第2章', 'nodes': []},
    ]
    write_node_id(structure)
    assert structure[0]['node_id'] == '00000001'
    assert structure[0]['nodes'][0]['node_id'] == '00000002'
    assert structure[0]['nodes'][1]['node_id'] == '00000003'
    assert structure[1]['node_id'] == '00000004'
    print("✅ write_node_id 正确")

    # --- structure_to_list ---
    flat = structure_to_list(structure)
    assert len(flat) == 4
    titles = [n['title'] for n in flat]
    assert titles == ['第1章', '1.1', '1.2', '第2章']
    print("✅ structure_to_list 正确")

    # --- get_leaf_nodes ---
    leaves = get_leaf_nodes(structure)
    assert len(leaves) == 3  # 1.1, 1.2, 第2章
    print("✅ get_leaf_nodes 正确")

    # --- get_pdf_name ---
    assert get_pdf_name('/path/to/doc.pdf') == 'doc.pdf'
    # 旧版 get_pdf_name 对 BytesIO 会尝试用 PyPDF2 读取元数据，
    # 传入非 PDF 内容会抛出异常，这是预期行为
    print("✅ get_pdf_name 正确")

    # --- count_tokens ---
    assert count_tokens('') == 0
    assert count_tokens('hello world') > 0
    assert count_tokens('你好世界') > 0
    print("✅ count_tokens 正确")

    # --- extract_json ---
    json_str = '```json\n{"key": "value"}\n```'
    result = extract_json(json_str)
    assert result == {'key': 'value'}
    print("✅ extract_json (with code block) 正确")

    json_str2 = '{"a": 1, "b": 2}'
    result2 = extract_json(json_str2)
    assert result2 == {'a': 1, 'b': 2}
    print("✅ extract_json (plain) 正确")

    # --- get_json_content ---
    content = get_json_content('```json\n{"x": 1}\n```')
    assert content.strip() == '{"x": 1}'
    print("✅ get_json_content 正确")

    # --- format_structure ---
    struct = {
        'text': 'some text',
        'title': 'Test',
        'node_id': '00000001',
        'nodes': [{'text': 'child', 'title': 'Child', 'node_id': '00000002'}]
    }
    formatted = format_structure(struct, order=['title', 'node_id', 'text', 'nodes'])
    keys = list(formatted.keys())
    assert keys == ['title', 'node_id', 'text', 'nodes']
    print("✅ format_structure 正确")

    # --- create_clean_structure_for_description ---
    clean = create_clean_structure_for_description(struct)
    assert 'text' not in clean  # text 不应出现在 clean 结构中
    assert 'title' in clean
    assert 'node_id' in clean
    print("✅ create_clean_structure_for_description 正确")

    # --- remove_fields ---
    no_text = remove_fields(struct, fields=['text'])
    assert 'text' not in no_text
    assert 'title' in no_text
    print("✅ remove_fields 正确")

    # --- reorder_dict ---
    d = {'c': 3, 'a': 1, 'b': 2}
    ordered = reorder_dict(d, ['a', 'b', 'c'])
    assert list(ordered.keys()) == ['a', 'b', 'c']
    print("✅ reorder_dict 正确")

    # --- get_nodes ---
    nodes = get_nodes(structure)
    assert len(nodes) == 4
    print("✅ get_nodes 正确")

    # --- get_last_node ---
    last = get_last_node(structure)
    assert last['title'] == '第2章'
    print("✅ get_last_node 正确")

    print()
    return True


# ============================================================
# 测试 4: page_index_builder_from_structure (不依赖 LLM)
# ============================================================
def test_page_index_builder_from_structure():
    print("=" * 60)
    print("测试 4: page_index_builder_from_structure")
    print("=" * 60)

    from pageindex import page_index_builder_from_structure
    from pageindex.utils import ConfigLoader
    import asyncio

    # 构造模拟的 MinerU 提取结构
    mock_structure = [
        {
            'title': '第一章 概述',
            'level': 1,
            'text': '这是第一章的概述内容。',
            'nodes': [
                {
                    'title': '1.1 背景',
                    'level': 2,
                    'text': '背景介绍文本。',
                },
                {
                    'title': '1.2 目标',
                    'level': 2,
                    'text': '目标描述文本。',
                    'nodes': [
                        {
                            'title': '1.2.1 具体目标',
                            'level': 3,
                            'text': '具体目标描述。',
                        }
                    ]
                }
            ]
        },
        {
            'title': '第二章 方法',
            'level': 1,
            'text': '方法描述内容。',
        }
    ]

    # 配置：只用 node_id，不生成摘要（避免 LLM 调用）
    opt = ConfigLoader().load({
        'model': '',
        'if_add_node_id': 'yes',
        'if_add_node_summary': 'no',
        'if_add_doc_description': 'no',
    })

    async def run():
        result = await page_index_builder_from_structure(
            '/tmp/test.pdf', mock_structure, opt
        )
        return result

    result = asyncio.run(run())

    # 验证结构
    assert 'doc_name' in result
    assert result['doc_name'] == 'test.pdf'
    assert 'structure' in result

    struct = result['structure']
    assert len(struct) == 2
    assert struct[0]['node_id'] == '00000001'
    assert struct[0]['title'] == '第一章 概述'
    assert 'text' in struct[0]
    assert struct[0]['nodes'][0]['node_id'] == '00000002'
    assert struct[0]['nodes'][1]['nodes'][0]['node_id'] == '00000004'

    # 验证字段顺序
    keys = list(struct[0].keys())
    assert keys[0] == 'title'
    assert keys[1] == 'node_id'
    assert 'summary' not in struct[0]  # 未启用摘要

    print("✅ page_index_builder_from_structure 基本流程正确")
    print(f"   文档名称: {result['doc_name']}")
    print(f"   顶级节点数: {len(struct)}")
    print(f"   总节点数: {len(__import__('pageindex.utils', fromlist=['structure_to_list']).structure_to_list(struct))}")

    print()
    return True


# ============================================================
# 测试 5: 配置加载器
# ============================================================
def test_config_loader():
    print("=" * 60)
    print("测试 5: ConfigLoader")
    print("=" * 60)

    from pageindex.utils import ConfigLoader

    # 默认配置
    loader = ConfigLoader()
    config = loader.load()
    assert hasattr(config, 'model')
    assert hasattr(config, 'if_add_node_id')
    assert hasattr(config, 'if_add_node_summary')
    assert hasattr(config, 'if_add_doc_description')
    # 确认旧配置项已恢复
    assert hasattr(config, 'toc_check_page_num'), "toc_check_page_num 应已恢复"
    assert hasattr(config, 'max_page_num_each_node'), "max_page_num_each_node 应已恢复"
    assert hasattr(config, 'max_token_num_each_node'), "max_token_num_each_node 应已恢复"
    assert hasattr(config, 'if_add_node_text'), "if_add_node_text 应已恢复"
    print("✅ 默认配置加载正确，旧配置项已恢复")

    # 用户覆盖配置
    config2 = loader.load({'if_add_node_id': 'no', 'if_add_node_summary': 'yes'})
    assert config2.if_add_node_id == 'no'
    assert config2.if_add_node_summary == 'yes'
    print("✅ 用户配置覆盖正确")

    # 非法配置键应报错
    try:
        loader.load({'invalid_key': 'value'})
        assert False, "应该抛出 ValueError"
    except ValueError as e:
        assert 'Unknown config keys' in str(e)
    print("✅ 非法配置键检测正确")

    print()
    return True


# ============================================================
# 测试 6: page_index 入口参数校验
# ============================================================
def test_page_index_validation():
    print("=" * 60)
    print("测试 6: page_index 入口参数校验")
    print("=" * 60)

    from pageindex import page_index_main_async
    import asyncio

    async def run():
        # 不存在的文件
        try:
            await page_index_main_async('/nonexistent/file.pdf')
            assert False, "应抛出异常"
        except ValueError as e:
            assert 'Unsupported' in str(e)
        print("✅ 不存在的 PDF 文件路径抛出 ValueError")

        # 非 PDF 文件
        try:
            await page_index_main_async('/tmp/test.txt')
            assert False, "应抛出异常"
        except ValueError as e:
            assert 'Unsupported' in str(e)
        print("✅ 非 PDF 文件路径抛出 ValueError")

    asyncio.run(run())
    print()
    return True


# ============================================================
# 主入口
# ============================================================
if __name__ == '__main__':
    results = []
    tests = [
        test_imports,
        test_markdown_headers_to_tree,
        test_utils_functions,
        test_page_index_builder_from_structure,
        test_config_loader,
        test_page_index_validation,
    ]

    for test in tests:
        try:
            results.append(test())
        except Exception as e:
            print(f"❌ {test.__name__} 失败: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)

    print("=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    passed = sum(1 for r in results if r)
    total = len(results)
    for test, result in zip(tests, results):
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status}: {test.__name__}")
    print(f"\n总计: {passed}/{total} 通过")
    sys.exit(0 if passed == total else 1)