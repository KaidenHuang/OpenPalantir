"""
PageIndex 工具函数

使用项目自身的 ModelClient（model_management）替代 litellm 进行 LLM 调用。
避免对外部 litellm 包的依赖，并与模型管理系统深度集成。
"""

import logging
import os
import re
import textwrap
import time
import json
import PyPDF2
import copy
import asyncio
from io import BytesIO
from dotenv import load_dotenv
import yaml
from pathlib import Path
from types import SimpleNamespace as config

load_dotenv()


# ── 全局模型配置（在调用 PageIndex 前由 model_adapter 设置）──
_pageindex_model_config = None  # dict 或 None，传递给 ModelClient 的配置


def set_model_config(model_config: dict):
    """设置全局模型配置，所有后续 LLM 调用将使用此配置。"""
    global _pageindex_model_config
    _pageindex_model_config = model_config


def clear_model_config():
    """清除全局模型配置。"""
    global _pageindex_model_config
    _pageindex_model_config = None


# ── Token 计数（轻量近似，无需外部依赖）──

_CHINESE_CHAR_RATIO = 1.5  # 中文字符与 token 的近似比例
_ENGLISH_CHAR_RATIO = 4.0  # 英文字符与 token 的近似比例


def count_tokens(text, model=None):
    """估算文本的 token 数量（无需外部 tokenizer）。"""
    if not text:
        return 0

    chinese_chars = sum(1 for c in text if '一' <= c <= '鿿')
    other_chars = len(text) - chinese_chars

    return int(chinese_chars / _CHINESE_CHAR_RATIO + other_chars / _ENGLISH_CHAR_RATIO)


# ── LLM 调用（使用 ModelClient）──

def _get_client():
    """从全局配置创建 ModelClient 实例。"""
    from model_management import ModelClient

    if _pageindex_model_config:
        return ModelClient(_pageindex_model_config)
    # 无配置时使用默认配置
    return ModelClient()


def _call_llm(prompt, system_prompt="你是一个AI助手。"):
    """调用 LLM 并返回原始响应文本（同步）。"""
    from model_management import ModelClient

    client = _get_client()

    if client.config.type == "local":
        response_text = client._call_local_model(
            prompt=prompt,
            expected_format="json",
            temperature=0,
            max_tokens=8192
        )
    else:
        response_text = client._call_cloud_model(
            prompt=prompt,
            system_prompt=system_prompt,
            expected_format="json_object",
            temperature=0,
            max_tokens=8192
        )
    return response_text


def llm_completion(model, prompt, chat_history=None, return_finish_reason=False,
                   api_key=None, api_base=None):
    """
    调用 LLM 并返回响应文本。

    参数 api_key / api_base 用于临时覆盖全局配置（用于兼容性）。
    """
    max_retries = 10
    messages = list(chat_history) + [{"role": "user", "content": prompt}] if chat_history else [{"role": "user", "content": prompt}]

    for i in range(max_retries):
        try:
            from model_management import ModelClient

            if _pageindex_model_config:
                client = ModelClient(_pageindex_model_config)
            else:
                client = ModelClient()

            # 如果调用方传入了临时 api_key/api_base，覆盖配置
            if api_key:
                client.config.api_key = api_key
            if api_base and client.config.type == "local":
                client.config.api_url = api_base
            elif api_base:
                client.config.api_url = api_base

            # 构造完整 prompt（含对话历史）
            full_prompt = ""
            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                full_prompt += f"{role}: {content}\n"

            if client.config.type == "local":
                response_text = client._call_local_model(
                    prompt=full_prompt,
                    expected_format="json",
                    temperature=0,
                    max_tokens=8192
                )
            else:
                response_text = client._call_cloud_model(
                    prompt=full_prompt,
                    system_prompt="你是一个AI助手。",
                    expected_format="json_object",
                    temperature=0,
                    max_tokens=8192
                )

            if response_text:
                if return_finish_reason:
                    return response_text, "finished"
                return response_text
            else:
                logging.warning(f"第 {i + 1} 次尝试：响应为空")

        except Exception as e:
            print('************* Retrying *************')
            logging.error(f"Error: {e}")
            if i < max_retries - 1:
                time.sleep(1)
            else:
                logging.error('Max retries reached for prompt: ' + prompt)
                if return_finish_reason:
                    return "", "error"
                return ""

    logging.error(f"LLM 调用在 {max_retries} 次重试后仍无有效响应")
    if return_finish_reason:
        return "", "error"
    return ""


async def llm_acompletion(model, prompt, api_key=None, api_base=None):
    """
    异步调用 LLM（内部使用线程池执行同步调用）。
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: llm_completion(model, prompt, api_key=api_key, api_base=api_base)
    )


def get_json_content(response):
    start_idx = response.find("```json")
    if start_idx != -1:
        start_idx += 7
        response = response[start_idx:]

    end_idx = response.rfind("```")
    if end_idx != -1:
        response = response[:end_idx]

    json_content = response.strip()
    return json_content


def extract_json(content):
    try:
        start_idx = content.find("```json")
        if start_idx != -1:
            start_idx += 7
            end_idx = content.rfind("```")
            json_content = content[start_idx:end_idx].strip()
        else:
            json_content = content.strip()

        json_content = json_content.replace('None', 'null')
        json_content = json_content.replace('\n', ' ').replace('\r', ' ')
        json_content = ' '.join(json_content.split())

        return json.loads(json_content)
    except json.JSONDecodeError as e:
        logging.error(f"Failed to extract JSON: {e}")
        try:
            json_content = json_content.replace(',]', ']').replace(',}', '}')
            return json.loads(json_content)
        except:
            logging.error("Failed to parse JSON even after cleanup")
            return {}
    except Exception as e:
        logging.error(f"Unexpected error while extracting JSON: {e}")
        return {}


def write_node_id(data, node_id=0):
    if isinstance(data, dict):
        data['node_id'] = str(node_id + 1).zfill(8)
        node_id += 1
        for key in list(data.keys()):
            if 'nodes' in key:
                node_id = write_node_id(data[key], node_id)
    elif isinstance(data, list):
        for index in range(len(data)):
            node_id = write_node_id(data[index], node_id)
    return node_id


def get_nodes(structure):
    if isinstance(structure, dict):
        structure_node = copy.deepcopy(structure)
        structure_node.pop('nodes', None)
        nodes = [structure_node]
        for key in list(structure.keys()):
            if 'nodes' in key:
                nodes.extend(get_nodes(structure[key]))
        return nodes
    elif isinstance(structure, list):
        nodes = []
        for item in structure:
            nodes.extend(get_nodes(item))
        return nodes


def structure_to_list(structure):
    if isinstance(structure, dict):
        nodes = []
        nodes.append(structure)
        if 'nodes' in structure:
            nodes.extend(structure_to_list(structure['nodes']))
        return nodes
    elif isinstance(structure, list):
        nodes = []
        for item in structure:
            nodes.extend(structure_to_list(item))
        return nodes


def get_leaf_nodes(structure):
    if isinstance(structure, dict):
        if not structure['nodes']:
            structure_node = copy.deepcopy(structure)
            structure_node.pop('nodes', None)
            return [structure_node]
        else:
            leaf_nodes = []
            for key in list(structure.keys()):
                if 'nodes' in key:
                    leaf_nodes.extend(get_leaf_nodes(structure[key]))
            return leaf_nodes
    elif isinstance(structure, list):
        leaf_nodes = []
        for item in structure:
            leaf_nodes.extend(get_leaf_nodes(item))
        return leaf_nodes


def is_leaf_node(data, node_id):
    def find_node(data, node_id):
        if isinstance(data, dict):
            if data.get('node_id') == node_id:
                return data
            for key in data.keys():
                if 'nodes' in key:
                    result = find_node(data[key], node_id)
                    if result:
                        return result
        elif isinstance(data, list):
            for item in data:
                result = find_node(item, node_id)
                if result:
                    return result
        return None

    node = find_node(data, node_id)
    if node and not node.get('nodes'):
        return True
    return False


def get_last_node(structure):
    return structure[-1]


def extract_text_from_pdf(pdf_path):
    pdf_reader = PyPDF2.PdfReader(pdf_path)
    text = ""
    for page_num in range(len(pdf_reader.pages)):
        page = pdf_reader.pages[page_num]
        text += page.extract_text()
    return text


def get_pdf_title(pdf_path):
    pdf_reader = PyPDF2.PdfReader(pdf_path)
    meta = pdf_reader.metadata
    title = meta.title if meta and meta.title else 'Untitled'
    return title


def get_text_of_pages(pdf_path, start_page, end_page, tag=True):
    pdf_reader = PyPDF2.PdfReader(pdf_path)
    text = ""
    for page_num in range(start_page-1, end_page):
        page = pdf_reader.pages[page_num]
        page_text = page.extract_text()
        if tag:
            text += f"<start_index_{page_num+1}>\n{page_text}\n<end_index_{page_num+1}>\n"
        else:
            text += page_text
    return text


def get_first_start_page_from_text(text):
    start_page = -1
    start_page_match = re.search(r'<start_index_(\d+)>', text)
    if start_page_match:
        start_page = int(start_page_match.group(1))
    return start_page


def get_last_start_page_from_text(text):
    start_page = -1
    start_page_matches = re.finditer(r'<start_index_(\d+)>', text)
    matches_list = list(start_page_matches)
    if matches_list:
        start_page = int(matches_list[-1].group(1))
    return start_page


def sanitize_filename(filename, replacement='-'):
    return filename.replace('/', replacement)


def get_pdf_name(pdf_path):
    if isinstance(pdf_path, str):
        pdf_name = os.path.basename(pdf_path)
    elif isinstance(pdf_path, BytesIO):
        pdf_reader = PyPDF2.PdfReader(pdf_path)
        meta = pdf_reader.metadata
        pdf_name = meta.title if meta and meta.title else 'Untitled'
        pdf_name = sanitize_filename(pdf_name)
    return pdf_name


def list_to_tree(data):
    def get_parent_structure(structure):
        if not structure:
            return None
        parts = str(structure).split('.')
        return '.'.join(parts[:-1]) if len(parts) > 1 else None

    nodes = {}
    root_nodes = []

    for item in data:
        structure = item.get('structure')
        node = {
            'title': item.get('title'),
            'start_index': item.get('start_index'),
            'end_index': item.get('end_index'),
            'nodes': []
        }
        nodes[structure] = node

        parent_structure = get_parent_structure(structure)

        if parent_structure:
            if parent_structure in nodes:
                nodes[parent_structure]['nodes'].append(node)
            else:
                root_nodes.append(node)
        else:
            root_nodes.append(node)

    def clean_node(node):
        if not node['nodes']:
            del node['nodes']
        else:
            for child in node['nodes']:
                clean_node(child)
        return node

    return [clean_node(node) for node in root_nodes]


def add_preface_if_needed(data):
    if not isinstance(data, list) or not data:
        return data

    if data[0]['physical_index'] is not None and data[0]['physical_index'] > 1:
        preface_node = {
            "structure": "0",
            "title": "Preface",
            "physical_index": 1,
        }
        data.insert(0, preface_node)
    return data


def get_page_tokens(pdf_path, model=None, pdf_parser="PyPDF2"):
    if pdf_parser == "PyPDF2":
        pdf_reader = PyPDF2.PdfReader(pdf_path)
        page_list = []
        for page_num in range(len(pdf_reader.pages)):
            page = pdf_reader.pages[page_num]
            page_text = page.extract_text()
            token_length = count_tokens(page_text, model=model)
            page_list.append((page_text, token_length))
        return page_list
    else:
        raise ValueError(f"Unsupported PDF parser: {pdf_parser}")


def get_text_of_pdf_pages(pdf_pages, start_page, end_page):
    text = ""
    for page_num in range(start_page-1, end_page):
        text += pdf_pages[page_num][0]
    return text


def get_text_of_pdf_pages_with_labels(pdf_pages, start_page, end_page):
    text = ""
    for page_num in range(start_page-1, end_page):
        text += f"<physical_index_{page_num+1}>\n{pdf_pages[page_num][0]}\n<physical_index_{page_num+1}>\n"
    return text


def get_number_of_pages(pdf_path):
    pdf_reader = PyPDF2.PdfReader(pdf_path)
    num = len(pdf_reader.pages)
    return num


def post_processing(structure, end_physical_index):
    for i, item in enumerate(structure):
        item['start_index'] = item.get('physical_index')
        if i < len(structure) - 1:
            if structure[i + 1].get('appear_start') == 'yes':
                item['end_index'] = structure[i + 1]['physical_index']-1
            else:
                item['end_index'] = structure[i + 1]['physical_index']
        else:
            item['end_index'] = end_physical_index
    tree = list_to_tree(structure)
    if len(tree)!=0:
        return tree
    else:
        for node in structure:
            node.pop('appear_start', None)
            node.pop('physical_index', None)
        return structure


def clean_structure_post(data):
    if isinstance(data, dict):
        data.pop('page_number', None)
        data.pop('start_index', None)
        data.pop('end_index', None)
        if 'nodes' in data:
            clean_structure_post(data['nodes'])
    elif isinstance(data, list):
        for section in data:
            clean_structure_post(section)
    return data


def remove_fields(data, fields=['text']):
    if isinstance(data, dict):
        return {k: remove_fields(v, fields)
            for k, v in data.items() if k not in fields}
    elif isinstance(data, list):
        return [remove_fields(item, fields) for item in data]
    return data


def print_toc(tree, indent=0):
    for node in tree:
        print('  ' * indent + node['title'])
        if node.get('nodes'):
            print_toc(node['nodes'], indent + 1)


def print_json(data, max_len=40, indent=2):
    def simplify_data(obj):
        if isinstance(obj, dict):
            return {k: simplify_data(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [simplify_data(item) for item in obj]
        elif isinstance(obj, str) and len(obj) > max_len:
            return obj[:max_len] + '...'
        else:
            return obj

    simplified = simplify_data(data)
    print(json.dumps(simplified, indent=indent, ensure_ascii=False))


def remove_structure_text(data):
    if isinstance(data, dict):
        data.pop('text', None)
        if 'nodes' in data:
            remove_structure_text(data['nodes'])
    elif isinstance(data, list):
        for item in data:
            remove_structure_text(item)
    return data


def check_token_limit(structure, limit=110000):
    lst = structure_to_list(structure)
    for node in lst:
        num_tokens = count_tokens(node['text'], model=None)
        if num_tokens > limit:
            print(f"Node ID: {node['node_id']} has {num_tokens} tokens")
            print("Start Index:", node['start_index'])
            print("End Index:", node['end_index'])
            print("Title:", node['title'])
            print("\n")


def convert_physical_index_to_int(data):
    if isinstance(data, list):
        for i in range(len(data)):
            if isinstance(data[i], dict) and 'physical_index' in data[i]:
                if isinstance(data[i]['physical_index'], str):
                    if data[i]['physical_index'].startswith('<physical_index_'):
                        data[i]['physical_index'] = int(data[i]['physical_index'].split('_')[-1].rstrip('>').strip())
                    elif data[i]['physical_index'].startswith('physical_index_'):
                        data[i]['physical_index'] = int(data[i]['physical_index'].split('_')[-1].strip())
    elif isinstance(data, str):
        if data.startswith('<physical_index_'):
            data = int(data.split('_')[-1].rstrip('>').strip())
        elif data.startswith('physical_index_'):
            data = int(data.split('_')[-1].strip())
        if isinstance(data, int):
            return data
        else:
            return None
    return data


def convert_page_to_int(data):
    for item in data:
        if 'page' in item and isinstance(item['page'], str):
            try:
                item['page'] = int(item['page'])
            except ValueError:
                pass
    return data


def add_node_text(node, pdf_pages):
    if isinstance(node, dict):
        start_page = node.get('start_index')
        end_page = node.get('end_index')
        node['text'] = get_text_of_pdf_pages(pdf_pages, start_page, end_page)
        if 'nodes' in node:
            add_node_text(node['nodes'], pdf_pages)
    elif isinstance(node, list):
        for index in range(len(node)):
            add_node_text(node[index], pdf_pages)
    return


def add_node_text_with_labels(node, pdf_pages):
    if isinstance(node, dict):
        start_page = node.get('start_index')
        end_page = node.get('end_index')
        node['text'] = get_text_of_pdf_pages_with_labels(pdf_pages, start_page, end_page)
        if 'nodes' in node:
            add_node_text_with_labels(node['nodes'], pdf_pages)
    elif isinstance(node, list):
        for index in range(len(node)):
            add_node_text_with_labels(node[index], pdf_pages)
    return


async def generate_node_summary(node, model=None, api_key=None, api_base=None):
    prompt_template_path = os.path.join(os.path.dirname(__file__), 'prompt_summary_node.md')
    try:
        with open(prompt_template_path, 'r', encoding='utf-8') as f:
            template = f.read()
    except FileNotFoundError:
        template = "请根据以下文本生成摘要描述：\n\n{text}"
    prompt = template.replace('{text}', node['text'])
    response = await llm_acompletion(model, prompt, api_key=api_key, api_base=api_base)
    return response


async def generate_summaries_for_structure(structure, model=None, api_key=None, api_base=None):
    nodes = structure_to_list(structure)
    tasks = [generate_node_summary(node, model=model, api_key=api_key, api_base=api_base) for node in nodes]
    summaries = await asyncio.gather(*tasks)

    for node, summary in zip(nodes, summaries):
        node['summary'] = summary
    return structure


def create_clean_structure_for_description(structure):
    if isinstance(structure, dict):
        clean_node = {}
        for key in ['title', 'node_id', 'summary', 'prefix_summary']:
            if key in structure:
                clean_node[key] = structure[key]
        if 'nodes' in structure and structure['nodes']:
            clean_node['nodes'] = create_clean_structure_for_description(structure['nodes'])
        return clean_node
    elif isinstance(structure, list):
        return [create_clean_structure_for_description(item) for item in structure]
    else:
        return structure


def generate_doc_description(structure, model=None, api_key=None, api_base=None):
    prompt_template_path = os.path.join(os.path.dirname(__file__), 'prompt_doc_description.md')
    try:
        with open(prompt_template_path, 'r', encoding='utf-8') as f:
            template = f.read()
    except FileNotFoundError:
        template = "请根据以下文档结构生成一句话描述：\n\n{structure}"
    prompt = template.replace('{structure}', str(structure))
    response = llm_completion(model, prompt, api_key=api_key, api_base=api_base)
    return response


def reorder_dict(data, key_order):
    if not key_order:
        return data
    return {key: data[key] for key in key_order if key in data}


def format_structure(structure, order=None):
    if not order:
        return structure
    if isinstance(structure, dict):
        if 'nodes' in structure:
            structure['nodes'] = format_structure(structure['nodes'], order)
        if not structure.get('nodes'):
            structure.pop('nodes', None)
        structure = reorder_dict(structure, order)
    elif isinstance(structure, list):
        structure = [format_structure(item, order) for item in structure]
    return structure


class ConfigLoader:
    def __init__(self, default_path: str = None):
        if default_path is None:
            default_path = Path(__file__).parent / "config.yaml"
        self._default_dict = self._load_yaml(default_path)

    @staticmethod
    def _load_yaml(path):
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _validate_keys(self, user_dict):
        unknown_keys = set(user_dict) - set(self._default_dict)
        if unknown_keys:
            raise ValueError(f"Unknown config keys: {unknown_keys}")

    def load(self, user_opt=None) -> config:
        if user_opt is None:
            user_dict = {}
        elif isinstance(user_opt, config):
            user_dict = vars(user_opt)
        elif isinstance(user_opt, dict):
            user_dict = user_opt
        else:
            raise TypeError("user_opt must be dict, config(SimpleNamespace) or None")

        self._validate_keys(user_dict)
        merged = {**self._default_dict, **user_dict}
        return config(**merged)


def create_node_mapping(tree):
    mapping = {}
    def _traverse(nodes):
        for node in nodes:
            if node.get('node_id'):
                mapping[node['node_id']] = node
            if node.get('nodes'):
                _traverse(node['nodes'])
    _traverse(tree)
    return mapping


def print_tree(tree, indent=0):
    for node in tree:
        summary = node.get('summary') or node.get('prefix_summary', '')
        summary_str = f"  —  {summary[:60]}..." if summary else ""
        print('  ' * indent + f"[{node.get('node_id', '?')}] {node.get('title', '')}{summary_str}")
        if node.get('nodes'):
            print_tree(node['nodes'], indent + 1)


def print_wrapped(text, width=100):
    for line in text.splitlines():
        print(textwrap.fill(line, width=width))
