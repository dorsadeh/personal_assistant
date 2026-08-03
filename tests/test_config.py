import pytest

from bot.config import load_config


def _env(**overrides):
    env = {
        "TELEGRAM_BOT_TOKEN": "123:abc",
        "ALLOWED_CHAT_IDS": "-100123, 456",
    }
    env.update(overrides)
    return {k: v for k, v in env.items() if v is not None}


def test_loads_token_and_chat_ids():
    config = load_config(_env())
    assert config.bot_token == "123:abc"
    assert config.allowed_chat_ids == {-100123, 456}


def test_defaults():
    config = load_config(_env())
    assert config.claude_bin == "claude"
    assert config.claude_timeout == 300
    assert config.workspace_dir.name == "workspace"
    assert config.data_dir.name == "data"


def test_missing_token_raises():
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        load_config(_env(TELEGRAM_BOT_TOKEN=None))


def test_missing_chat_ids_raises():
    with pytest.raises(ValueError, match="ALLOWED_CHAT_IDS"):
        load_config(_env(ALLOWED_CHAT_IDS=""))
