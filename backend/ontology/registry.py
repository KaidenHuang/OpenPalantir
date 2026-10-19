"""
本体注册表 — 加载/校验/合并 YAML 本体包，提供受控词表查询与谓词归一化

general 为基底包，其余域包在其上扩展（同 key 覆盖）；包可用 extends 声明挂在某个
域包之上，形成扩展链，社区包因此只写增量而不必整包 fork 内置域。
内置包在 ontology/packs/，社区/自定义包在 data/ontology_packs/（同名以后者为准），
导入即校验、导出即回读，社区提交的包走同一条校验链。
谓词归一化：exact key → 别名（大小写/空白不敏感），无法归一返回 None，
由调用方决定拒绝或兜底。
"""
import os
import re
import threading
from typing import Dict, List, Optional, Tuple

import yaml

from .types import LinkType, ObjectType, OntologyError, OntologyPack, PropertyType

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "packs")
USER_PACKS_DIR = os.path.join(BACKEND_DIR, "data", "ontology_packs")
BASE_PACK = "general"


def _norm(text: str) -> str:
    return (text or "").strip().lower().replace(" ", "")


def _parse_object_type(raw: dict) -> ObjectType:
    props = [PropertyType(key=p["key"], data_type=p.get("data_type", "string"),
                          description=p.get("description", ""))
             for p in raw.get("properties", []) or []]
    return ObjectType(
        key=raw["key"],
        display_name=raw.get("display_name", raw["key"]),
        description=raw.get("description", ""),
        parent=raw.get("parent") or None,
        color=raw.get("color", "#95A5A6"),
        sort_order=raw.get("sort_order", 0),
        properties=props,
    )


def _parse_link_type(raw: dict) -> LinkType:
    return LinkType(
        key=raw["key"],
        display_name=raw.get("display_name", raw["key"]),
        description=raw.get("description", ""),
        domain=list(raw.get("domain", []) or []),
        range=list(raw.get("range", []) or []),
        symmetric=bool(raw.get("symmetric", False)),
        inverse=raw.get("inverse") or None,
        aliases=[a for a in (raw.get("aliases", []) or []) if a],
    )


def parse_pack(raw: dict) -> OntologyPack:
    if not raw.get("name"):
        raise OntologyError("本体包缺少 name")
    return OntologyPack(
        name=raw["name"],
        description=raw.get("description", ""),
        object_types=[_parse_object_type(t) for t in raw.get("object_types", []) or []],
        link_types=[_parse_link_type(t) for t in raw.get("link_types", []) or []],
        extends=raw.get("extends") or None,
    )


def validate_pack(pack: OntologyPack, base: Optional[OntologyPack] = None) -> List[str]:
    """校验单个包（相对基底），返回错误列表；空列表 = 合法"""
    errors: List[str] = []
    known_types: set = set()
    if base:
        known_types.update(o.key for o in base.object_types)
    object_keys = [o.key for o in pack.object_types]
    if len(object_keys) != len(set(object_keys)):
        errors.append("object_types 存在重复 key")
    known_types.update(object_keys)

    for o in pack.object_types:
        if o.parent and o.parent not in known_types:
            errors.append(f"ObjectType {o.key} 的 parent {o.parent} 不存在")

    link_keys = [l.key for l in pack.link_types]
    all_links: Dict[str, LinkType] = {}
    if base:
        all_links.update({l.key: l for l in base.link_types})
    if len(link_keys) != len(set(link_keys)):
        errors.append("link_types 存在重复 key")
    all_links.update({l.key: l for l in pack.link_types})

    for l in pack.link_types:
        for t in l.domain:
            if t not in known_types:
                errors.append(f"LinkType {l.key} 的 domain 类型 {t} 不存在")
        for t in l.range:
            if t not in known_types:
                errors.append(f"LinkType {l.key} 的 range 类型 {t} 不存在")
        if l.inverse and l.inverse not in all_links:
            errors.append(f"LinkType {l.key} 的 inverse {l.inverse} 未定义")
    return errors


def merge_packs(base: OntologyPack, pack: OntologyPack) -> OntologyPack:
    """域包覆盖基底包：同 key 覆盖，新 key 追加"""
    objects: Dict[str, ObjectType] = {o.key: o for o in base.object_types}
    objects.update({o.key: o for o in pack.object_types})
    links: Dict[str, LinkType] = {l.key: l for l in base.link_types}
    links.update({l.key: l for l in pack.link_types})
    return OntologyPack(
        name=pack.name,
        description=pack.description,
        object_types=sorted(objects.values(), key=lambda o: (o.sort_order, o.key)),
        link_types=list(links.values()),
    )


def build_views(packs: Dict[str, OntologyPack]) -> Dict[str, OntologyPack]:
    """逐包相对其父视图校验并算出全部域视图；extends 缺包/成环或任一包非法 → 整体拒绝"""
    base = packs.get(BASE_PACK)
    if base is None:
        raise OntologyError(f"缺少基底本体包: {BASE_PACK}")
    errors = validate_pack(base)
    if errors:
        raise OntologyError(f"general 包非法: {errors}")

    views: Dict[str, OntologyPack] = {BASE_PACK: base}

    def view_of(name: str, path: frozenset) -> OntologyPack:
        if name in views:
            return views[name]
        if name in path:
            raise OntologyError(f"本体包 extends 形成环: {name}")
        pack = packs.get(name)
        if pack is None:
            raise OntologyError(f"本体包 extends 的包不存在: {name}")
        parent = view_of(pack.extends or BASE_PACK, path | {name})
        errors = validate_pack(pack, base=parent)
        if errors:
            raise OntologyError(f"本体包 {name} 非法: {errors}")
        views[name] = merge_packs(parent, pack)
        return views[name]

    for name in packs:
        view_of(name, frozenset())
    return views


def pack_to_dict(pack: OntologyPack) -> dict:
    """本体包 → 可序列化字典（只写有值的字段，导出的 YAML 与人写的同构）"""
    objects = []
    for o in pack.object_types:
        item = {"key": o.key, "display_name": o.display_name}
        if o.description:
            item["description"] = o.description
        if o.parent:
            item["parent"] = o.parent
        if o.color and o.color != "#95A5A6":
            item["color"] = o.color
        if o.sort_order:
            item["sort_order"] = o.sort_order
        if o.properties:
            item["properties"] = [{"key": p.key, "data_type": p.data_type,
                                   "description": p.description} for p in o.properties]
        objects.append(item)

    links = []
    for l in pack.link_types:
        item = {"key": l.key, "display_name": l.display_name}
        if l.description:
            item["description"] = l.description
        if l.domain:
            item["domain"] = list(l.domain)
        if l.range:
            item["range"] = list(l.range)
        if l.symmetric:
            item["symmetric"] = True
        if l.inverse:
            item["inverse"] = l.inverse
        if l.aliases:
            item["aliases"] = list(l.aliases)
        links.append(item)

    return {"name": pack.name, "description": pack.description,
            "object_types": objects, "link_types": links,
            **({"extends": pack.extends} if pack.extends else {})}


def pack_to_yaml(pack: OntologyPack) -> str:
    return yaml.safe_dump(pack_to_dict(pack), allow_unicode=True,
                          sort_keys=False, default_flow_style=False)


class OntologyRegistry:
    """本体注册表：包加载、域视图、谓词归一化、社区包导入导出"""

    def __init__(self, packs_dir: str = PACKS_DIR, user_packs_dir: str = USER_PACKS_DIR):
        self._packs_dir = packs_dir
        self._user_packs_dir = user_packs_dir
        self._lock = threading.Lock()
        self._packs: Dict[str, OntologyPack] = {}
        self._views: Dict[str, OntologyPack] = {}
        self._alias_index: Dict[str, Dict[str, str]] = {}
        self._loaded = False
        self._version = 0

    @property
    def version(self) -> int:
        """本体变更版本号：每次包注册/重载后自增，供下游缓存键控"""
        return self._version

    # ── 加载 ──

    def _pack_files(self) -> List[str]:
        """内置包 + 用户包，同名以用户包为准"""
        found: Dict[str, str] = {}
        for directory in (self._packs_dir, self._user_packs_dir):
            if not os.path.isdir(directory):
                continue
            for fname in sorted(os.listdir(directory)):
                if fname.endswith((".yaml", ".yml")):
                    found[os.path.splitext(fname)[0]] = os.path.join(directory, fname)
        return [found[key] for key in sorted(found)]

    def load(self) -> None:
        with self._lock:
            if self._loaded:
                return
            packs: Dict[str, OntologyPack] = {}
            for path in self._pack_files():
                with open(path, "r", encoding="utf-8") as f:
                    raw = yaml.safe_load(f)
                pack = parse_pack(raw or {})
                packs[pack.name] = pack
            views = build_views(packs)
            self._packs = packs
            self._views = views
            self._alias_index = {}
            self._loaded = True

    def reload(self, packs_dir: Optional[str] = None) -> None:
        with self._lock:
            self._loaded = False
            if packs_dir:
                self._packs_dir = packs_dir
        self.load()
        with self._lock:
            self._version += 1

    def register_pack(self, pack: OntologyPack) -> None:
        """运行期注册外部本体包（社区包导入用）；校验不过则注册表原样不动"""
        self.load()
        with self._lock:
            packs = dict(self._packs)
            packs[pack.name] = pack
            views = build_views(packs)
            self._packs = packs
            self._views = views
            self._alias_index = {}
            self._version += 1

    # ── 导入 / 导出 ──

    def export_pack(self, domain: str) -> str:
        """导出域包为 YAML（导出的文本可原样再导入）"""
        self.load()
        if domain not in self._packs:
            raise OntologyError(f"本体包不存在: {domain}")
        return pack_to_yaml(self._packs[domain])

    def import_pack(self, text: str, persist: bool = False) -> OntologyPack:
        """导入社区/自定义包：校验不过直接拒绝；persist 时落到用户包目录，重启后仍在"""
        pack = parse_pack(yaml.safe_load(text) or {})
        if persist:
            if pack.name == BASE_PACK:
                raise OntologyError("基底包 general 不允许覆盖")
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", pack.name):
                raise OntologyError(f"包名只允许字母数字/下划线/连字符: {pack.name!r}")
        self.register_pack(pack)
        if persist:
            os.makedirs(self._user_packs_dir, exist_ok=True)
            path = os.path.join(self._user_packs_dir, f"{pack.name}.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(pack_to_yaml(pack))
        return pack

    # ── 查询 ──

    def domains(self) -> List[str]:
        self.load()
        return sorted(self._packs.keys())

    def pack(self, domain: str) -> OntologyPack:
        """域视图（general ⊕ extends 链 ⊕ 本包，加载时已算好）；未知域回落基底"""
        self.load()
        with self._lock:
            return self._views.get(domain or BASE_PACK) or self._views[BASE_PACK]

    def object_types(self, domain: str = BASE_PACK) -> List[ObjectType]:
        return self.pack(domain).object_types

    def link_types(self, domain: str = BASE_PACK) -> List[LinkType]:
        return self.pack(domain).link_types

    def get_object_type(self, key: str, domain: str = BASE_PACK) -> Optional[ObjectType]:
        for o in self.object_types(domain):
            if o.key == key:
                return o
        return None

    def get_link_type(self, key: str, domain: str = BASE_PACK) -> Optional[LinkType]:
        for l in self.link_types(domain):
            if l.key == key:
                return l
        return None

    def is_valid_object_type(self, key: str, domain: str = BASE_PACK) -> bool:
        return self.get_object_type(key, domain) is not None

    def all_link_keys(self) -> List[str]:
        """所有域视图的 LinkType key 并集（排序稳定，供索引预建/白名单校验）"""
        keys: set = set()
        for d in self.domains():
            keys.update(l.key for l in self.link_types(d))
        return sorted(keys)

    def is_link_key(self, key: str) -> bool:
        for d in self.domains():
            if self.get_link_type(key, d):
                return True
        return False

    # ── 谓词归一化 ──

    def _aliases(self, domain: str) -> Dict[str, str]:
        with self._lock:
            index = self._alias_index.get(domain)
        if index is not None:
            return index
        index = {}
        for l in self.link_types(domain):
            index[_norm(l.key)] = l.key
            for a in l.aliases:
                index.setdefault(_norm(a), l.key)
        with self._lock:
            self._alias_index[domain] = index
        return index

    def resolve_predicate(self, raw: str, domain: str = BASE_PACK) -> Optional[str]:
        """任意谓词文本 → 受控 LinkType key；无法归一返回 None"""
        if not raw:
            return None
        link = self.get_link_type(raw.strip(), domain)
        if link:
            return link.key
        return self._aliases(domain).get(_norm(raw))

    def resolve_predicate_any(self, raw: str) -> Optional[str]:
        """跨所有域解析谓词（general 优先，再逐域包）"""
        if not raw:
            return None
        for d in self.domains():
            key = self.resolve_predicate(raw, d)
            if key:
                return key
        return None

    def validate_predicate_types(self, predicate: str, subject_type: str,
                                 object_type: str, domain: str = BASE_PACK
                                 ) -> Tuple[bool, str]:
        """校验谓词的定义域/值域。返回 (是否合法, 原因)"""
        link = self.get_link_type(predicate, domain)
        if not link:
            return False, f"谓词 {predicate} 不在受控词表"
        if subject_type and not link.allows_subject(subject_type):
            return False, f"{predicate} 的主语类型 {subject_type} 超出定义域"
        if object_type and not link.allows_object(object_type):
            return False, f"{predicate} 的宾语类型 {object_type} 超出值域"
        return True, ""


ontology_registry = OntologyRegistry()
