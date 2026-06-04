import os
from abc import ABC, abstractmethod
from glob import glob
from typing import Dict, List

from system.logger import logger
from decision_engine.contracts import AnalyzedQuery, RawEvidence

DATA_SUMMARIES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "summaries")


class BaseRetriever(ABC):
    source_type: str = ""

    @abstractmethod
    def retrieve(self, query: AnalyzedQuery, context: Dict) -> List[RawEvidence]:
        ...

    @staticmethod
    def calc_score(text: str, keywords: set) -> float:
        if not keywords:
            return 0.0
        text_lower = text.lower()
        matches = sum(1 for kw in keywords if kw.lower() in text_lower)
        return matches / len(keywords) if matches > 0 else 0.0

    @staticmethod
    def extract_uuid_from_path(file_path: str, resource_type: str) -> str:
        parts = file_path.replace("\\", "/").split("/")
        try:
            idx = parts.index(resource_type)
            return parts[idx + 1] if idx + 1 < len(parts) else ""
        except (ValueError, IndexError):
            return ""

    @staticmethod
    def glob_summary_files(resource_dir: str) -> List[str]:
        summaries_dir = os.path.abspath(DATA_SUMMARIES_DIR)
        return glob(os.path.join(summaries_dir, resource_dir, "*", "*.json"))
