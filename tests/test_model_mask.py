"""API key 掩码与回填防护（纯函数级）"""
import pytest

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


@pytest.mark.unit
class TestModelServiceReadPaths:
    """读路径不得把 DB 故障降级成「不存在 / 空列表」，否则路由里已有的 500 分支永远走不到"""

    def test_db_failure_propagates(self):
        from model_management.model_service import ModelService

        class BrokenSession:
            def query(self, *args, **kwargs):
                raise RuntimeError("database is locked")

        broken = BrokenSession()
        with pytest.raises(RuntimeError):
            ModelService.get_all_models(broken)
        with pytest.raises(RuntimeError):
            ModelService.get_model(broken, 1)
        with pytest.raises(RuntimeError):
            ModelService.get_available_model(broken)

    def test_empty_db_is_business_state_not_error(self, db_session):
        from model_management.model_service import ModelService

        assert ModelService.get_all_models(db_session) == []
        assert ModelService.get_model(db_session, 1) is None
        assert ModelService.get_available_model(db_session) is None

    def test_available_model_config_uses_internal_key(self, db_session):
        """库记录的 model_type 在出口映射成 type，内部配置只有一个键名"""
        from model_management.model_service import ModelService
        from models.model import ModelInfo

        db_session.add(ModelInfo(name="m", type="cloud", status="available",
                                 models=["gpt"], enabled=True, api_key="k"))
        db_session.commit()
        config = ModelService.get_available_model(db_session)
        assert config["type"] == "cloud"
        assert config["api_key"] == "k"
        assert "model_type" not in config

    def test_from_dict_does_not_read_model_type(self):
        from model_management.model_client import ModelConfig

        assert ModelConfig.from_dict({"model_type": "cloud"}).type == "local"
