"""Tests for agentd.config"""

import os
import pytest
from unittest.mock import patch

from agentd.config import (
    AgentDConfig,
    OutputMode,
    get_config,
    configure,
    reset_config,
)


@pytest.fixture(autouse=True)
def reset_global_config():
    """Reset global config before each test."""
    reset_config()
    yield
    reset_config()


class TestAgentDConfig:
    def test_default_values(self):
        config = AgentDConfig()
        assert config.endpoint_url is None
        assert config.api_key is None
        assert config.agent_id is None
        assert config.session_id is None
        assert config.include_trace is True
        assert config.include_prompt is False
        assert config.include_tool_inputs is True
        assert config.include_tool_outputs is True
        assert config.truncate_outputs_at == 10000
        assert config.streaming is False
        assert config.default_metadata == {}

    def test_mode_defaults_to_console_when_no_url(self):
        config = AgentDConfig()
        assert config.mode == OutputMode.CONSOLE

    def test_mode_is_http_when_url_provided(self):
        config = AgentDConfig(endpoint_url="https://example.com")
        assert config.mode == OutputMode.HTTP

    def test_mode_is_disabled_when_disabled_flag(self):
        config = AgentDConfig(disabled=True)
        assert config.mode == OutputMode.DISABLED


class TestGetConfigFromEnv:
    def test_loads_url_from_env(self):
        with patch.dict(os.environ, {"AGENTD_URL": "https://test.com"}, clear=False):
            config = get_config()
            assert config.endpoint_url == "https://test.com"
            assert config.mode == OutputMode.HTTP

    def test_loads_api_key_from_env(self):
        with patch.dict(os.environ, {"AGENTD_API_KEY": "secret-key"}, clear=False):
            config = get_config()
            assert config.api_key == "secret-key"

    def test_loads_agent_id_from_env(self):
        with patch.dict(os.environ, {"AGENTD_AGENT_ID": "my-agent"}, clear=False):
            config = get_config()
            assert config.agent_id == "my-agent"

    def test_disabled_from_env(self):
        with patch.dict(os.environ, {"AGENTD_DISABLED": "true"}, clear=False):
            config = get_config()
            assert config.mode == OutputMode.DISABLED

    def test_disabled_case_insensitive(self):
        with patch.dict(os.environ, {"AGENTD_DISABLED": "TRUE"}, clear=False):
            config = get_config()
            assert config.mode == OutputMode.DISABLED

    def test_streaming_from_env(self):
        with patch.dict(os.environ, {"AGENTD_STREAMING": "true"}, clear=False):
            config = get_config()
            assert config.streaming is True

    def test_empty_env_uses_console_mode(self):
        # Ensure no AGENTD_* vars are set
        env_copy = {k: v for k, v in os.environ.items() if not k.startswith("AGENTD_")}
        with patch.dict(os.environ, env_copy, clear=True):
            config = get_config()
            assert config.endpoint_url is None
            assert config.mode == OutputMode.CONSOLE


class TestGetConfig:
    def test_returns_cached_config(self):
        config1 = get_config()
        config2 = get_config()
        assert config1 is config2

    def test_reset_clears_cache(self):
        config1 = get_config()
        reset_config()
        config2 = get_config()
        assert config1 is not config2


class TestConfigure:
    def test_configure_sets_values(self):
        configure(
            agent_id="configured-agent",
            include_trace=False,
            include_prompt=True,
        )

        config = get_config()
        assert config.agent_id == "configured-agent"
        assert config.include_trace is False
        assert config.include_prompt is True

    def test_configure_with_endpoint(self):
        configure(endpoint_url="https://custom.endpoint.com")
        config = get_config()
        assert config.endpoint_url == "https://custom.endpoint.com"
        assert config.mode == OutputMode.HTTP

    def test_configure_with_metadata(self):
        configure(default_metadata={"app": "test", "version": "1.0"})
        config = get_config()
        assert config.default_metadata["app"] == "test"
        assert config.default_metadata["version"] == "1.0"

    def test_configure_truncation(self):
        configure(truncate_outputs_at=5000)
        config = get_config()
        assert config.truncate_outputs_at == 5000

    def test_configure_disabled(self):
        configure(disabled=True)
        config = get_config()
        assert config.mode == OutputMode.DISABLED


class TestOutputMode:
    def test_output_mode_values(self):
        assert OutputMode.CONSOLE.value == "console"
        assert OutputMode.HTTP.value == "http"
        assert OutputMode.DISABLED.value == "disabled"
