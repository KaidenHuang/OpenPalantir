"""CSV/TSV 转换器 —— 与 xlsx 共用 table_reader 的表档案口径，单文件即单表

列数 ≤ 1 的「表格」不当表格处理（一行一句话的那种其实是 txt）：
read_tables 判成 single_column 后由 build_document 抛错，让调用方按文本处理。
"""
from ..table_reader import build_document

extract_csv = build_document
