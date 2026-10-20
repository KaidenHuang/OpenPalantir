"""XLSX/XLSM 转换器 —— 一个工作表一个一级章节，正文为该表的确定性表档案

行明细不进章节正文（④ 用 table_reader.iter_table_rows 重读源文件取），
② 只做解析，无 LLM。两种表格源共用 table_reader 的读取与渲染，这里只登记扩展名。
"""
from ..table_reader import build_document

extract_xlsx = build_document
