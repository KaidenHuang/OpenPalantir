"""API key 掩码与回填防护（纯函数级）"""
from models.model import API_KEY_MASK, mask_api_key


def test_mask_full_key_keeps_head_tail():
    masked = mask_api_key("sk-1234567890abcdef")
    assert masked == "sk-1****cdef"


def test_mask_short_key_full_cover():
    assert mask_api_key("short") == API_KEY_MASK


def test_mask_empty():
    assert mask_api_key("") == ""


def test_mask_idempotent():
    masked = mask_api_key("sk-1234567890abcdef")
    assert mask_api_key(masked) == masked


def test_mask_marker_is_dictinct_string():
    # 掩码标记不得与真实密钥形态混淆（Service 层据此判定「回传掩码 → 保留原值」）
    assert API_KEY_MASK == "****"
