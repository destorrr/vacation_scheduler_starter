import pytest
from pydantic import ValidationError

from app.config import Settings


def test_settings_accept_strong_secret_and_valid_session_age():
    settings = Settings(
        _env_file=None,
        secret_key="a" * 64,
        session_max_age=3600,
    )

    assert settings.secret_key == "a" * 64
    assert settings.session_max_age == 3600


@pytest.mark.parametrize(
    "secret",
    [
        "CHANGE_ME_BEFORE_DEPLOYMENT",
        "replace-with-a-long-random-secret-at-least-32-characters",
        "short",
    ],
)
def test_settings_reject_placeholder_or_short_secret(secret):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, secret_key=secret)


@pytest.mark.parametrize("age", [0, 299, 2_592_001])
def test_settings_reject_unreasonable_session_lifetime(age):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, secret_key="a" * 64, session_max_age=age)
