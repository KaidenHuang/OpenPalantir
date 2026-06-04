import os
import PyPDF2
from docx import Document
import markdown
import re
from PIL import Image
import pytesseract
from system.logger import logger

class DocumentProcessor:
    """文档处理器"""
    
    def __init__(self):
        pass
    
    def process_document(self, file_path):
        """处理文档，根据文件类型调用相应的处理方法"""
        logger.info(f"开始处理文档: {file_path}")
        file_extension = os.path.splitext(file_path)[1].lower()
        logger.info(f"识别文件类型: {file_extension}")
        
        try:
            if file_extension == '.txt':
                result = self.process_txt(file_path)
            elif file_extension == '.pdf':
                result = self.process_pdf(file_path)
            elif file_extension == '.docx':
                result = self.process_docx(file_path)
            elif file_extension == '.md':
                result = self.process_markdown(file_path)
            elif file_extension in ['.jpg', '.jpeg', '.png', '.bmp']:
                result = self.process_image(file_path)
            else:
                raise ValueError(f"不支持的文件类型: {file_extension}")
            
            logger.info(f"文档处理成功: {file_path}, 类型: {result['metadata']['file_type']}")
            return result
        except Exception as e:
            logger.error(f"文档处理失败: {file_path}, 错误: {str(e)}")
            raise
    
    def process_txt(self, file_path):
        """处理TXT文件"""
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        return {
            'content': content,
            'metadata': {
                'file_type': 'txt',
                'word_count': len(content.split()),
                'char_count': len(content)
            }
        }
    
    def process_pdf(self, file_path):
        """处理PDF文件"""
        content = []
        with open(file_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            for page_num in range(len(reader.pages)):
                page = reader.pages[page_num]
                content.append(page.extract_text())
        content = '\n'.join(content)
        return {
            'content': content,
            'metadata': {
                'file_type': 'pdf',
                'page_count': len(reader.pages),
                'word_count': len(content.split()),
                'char_count': len(content)
            }
        }
    
    def process_docx(self, file_path):
        """处理DOCX文件"""
        doc = Document(file_path)
        content = []
        for paragraph in doc.paragraphs:
            content.append(paragraph.text)
        content = '\n'.join(content)
        return {
            'content': content,
            'metadata': {
                'file_type': 'docx',
                'word_count': len(content.split()),
                'char_count': len(content)
            }
        }
    
    def process_markdown(self, file_path):
        """处理Markdown文件"""
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        return {
            'content': content,
            'metadata': {
                'file_type': 'markdown',
                'word_count': len(content.split()),
                'char_count': len(content)
            }
        }
    
    def process_image(self, file_path):
        """处理图片文件（OCR）"""
        try:
            image = Image.open(file_path)
            content = pytesseract.image_to_string(image, lang='chi_sim')
            return {
                'content': content,
                'metadata': {
                    'file_type': 'image',
                    'word_count': len(content.split()),
                    'char_count': len(content)
                }
            }
        except Exception as e:
            raise ValueError(f"OCR处理失败: {str(e)}")
    
    def split_into_chapters(self, content):
        """将文档内容切分为章节"""
        # 简单的章节切分逻辑，可根据实际需求调整
        chapters = re.split(r'[\n\r]+第[一二三四五六七八九十百千]+章[\n\r]+', content)
        return chapters
    
    def extract_metadata(self, content):
        """从文档内容中提取元数据"""
        # 这里可以实现更复杂的元数据提取逻辑
        return {
            'word_count': len(content.split()),
            'char_count': len(content),
            'line_count': len(content.split('\n'))
        }


# 创建全局文档处理器实例
document_processor = DocumentProcessor()