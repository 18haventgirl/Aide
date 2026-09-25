"""runtime_config 的端口与 CORS 解析"""

import importlib

import pytest


_VARS = (
    "API_HOST",
    "API_PORT",
    "MCP_HOST",
    "MCP_PORT",
    "MCP_PATH",
    "MCP_SERVER_URL",
    "UI_PORT",
    "CORS_ORIGINS",
)


@pytest.fixture
def load_config(monkeypatch):
    """按给定环境变量重新加载配置模块，未给出的变量清空以取回默认值"""

    def _load(**overrides: str):
        for name in _VARS:
            if name in overrides:
                monkeypatch.setenv(name, overrides[name])
            else:
                monkeypatch.delenv(name, raising=False)
        module = importlib.import_module("core.runtime_config")
        return importlib.reload(module)

    yield _load

    for name in _VARS:
        monkeypatch.delenv(name, raising=False)
    importlib.reload(importlib.import_module("core.runtime_config"))


def test_default_ports_avoid_legacy_8000_and_8002(load_config):
    cfg = load_config().RuntimeConfig

    assert cfg.API_PORT == 8100
    assert cfg.MCP_PORT == 8102
    assert cfg.MCP_SERVER_URL == "http://127.0.0.1:8102/mcp"


def test_mcp_url_follows_overridden_port(load_config):
    cfg = load_config(MCP_PORT="9200", UI_PORT="4321").RuntimeConfig

    assert cfg.MCP_SERVER_URL == "http://127.0.0.1:9200/mcp"


def test_explicit_mcp_url_wins(load_config):
    cfg = load_config(
        MCP_PORT="9200",
        MCP_SERVER_URL="http://10.0.0.5:8080/mcp",
    ).RuntimeConfig

    assert cfg.MCP_SERVER_URL == "http://10.0.0.5:8080/mcp"


def test_cors_origins_from_env(load_config):
    origins = load_config(
        CORS_ORIGINS="https://lg-aide.example.com, http://localhost:4321"
    ).cors_origins()

    assert origins == ["https://lg-aide.example.com", "http://localhost:4321"]


def test_default_cors_origins_cover_ui_port_and_never_wildcard(load_config):
    module = load_config(UI_PORT="4321")

    origins = module.cors_origins()

    assert "http://localhost:4321" in origins
    assert "http://127.0.0.1:4321" in origins
    assert "*" not in origins


def test_non_numeric_port_fails_loudly(load_config):
    with pytest.raises(ValueError, match="API_PORT"):
        load_config(API_PORT="not-a-port")


def test_api_origin_normalises_wildcard_bind(load_config):
    cfg = load_config(API_HOST="0.0.0.0", API_PORT="8100").RuntimeConfig

    assert cfg.api_origin() == "http://127.0.0.1:8100"
    assert cfg.api_origin("ws") == "ws://127.0.0.1:8100"
