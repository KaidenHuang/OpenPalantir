from enum import Enum
from uuid import uuid4
import re


class ResourceType(str, Enum):
    DOC = "DOC"
    DBS = "DBS"


class ResourceIdentifier:
    """统一资源标识符 {TYPE}://{UUID}/{路径}"""

    def __init__(self, type: ResourceType, uuid: str, path: str = ""):
        self.type = type
        self.uuid = uuid
        self.path = path

    @property
    def uri(self) -> str:
        if self.path:
            return f"{self.type.value}://{self.uuid}/{self.path}"
        return f"{self.type.value}://{self.uuid}"

    @property
    def file_safe_name(self) -> str:
        safe_path = self.path.replace("/", "_").replace(":", "_") if self.path else ""
        if safe_path:
            return f"{self.type.value}_{self.uuid}_{safe_path}"
        return f"{self.type.value}_{self.uuid}"

    @classmethod
    def parse(cls, uri: str) -> "ResourceIdentifier":
        m = re.match(r"^(\w+)://([^/]+?)(?:/(.*))?$", uri)
        if not m:
            raise ValueError(f"Invalid resource URI: {uri}")
        return cls(type=ResourceType(m.group(1)), uuid=m.group(2), path=m.group(3) or "")

    @classmethod
    def generate(cls, type: ResourceType, path: str = "") -> "ResourceIdentifier":
        return cls(type=type, uuid=str(uuid4()), path=path)

    def __eq__(self, other):
        if not isinstance(other, ResourceIdentifier):
            return NotImplemented
        return self.uri == other.uri

    def __hash__(self):
        return hash(self.uri)

    def __str__(self):
        return self.uri

    def __repr__(self):
        return f"ResourceIdentifier({self.uri})"
