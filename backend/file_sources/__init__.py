from file_sources.base import BaseFileSource, FileContent
from file_sources.local_source import LocalFileSource

_default_source = None


def get_default_source() -> BaseFileSource:
    global _default_source
    if _default_source is None:
        _default_source = LocalFileSource()
    return _default_source
