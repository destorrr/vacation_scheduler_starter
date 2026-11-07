import pytest

from app.security import csrf_is_valid, hash_password, new_csrf_token, verify_password


def test_password_hash_and_verify():
    password = "Correct-Horse-Battery-42!"
    password_hash = hash_password(password)

    assert password_hash != password
    assert verify_password(password_hash, password)
    assert not verify_password(password_hash, "wrong-password")


def test_password_minimum_length():
    with pytest.raises(ValueError):
        hash_password("short")


def test_csrf_token_validation():
    token = new_csrf_token()

    assert csrf_is_valid(token, token)
    assert not csrf_is_valid(token, "different")
    assert not csrf_is_valid(None, token)
    assert not csrf_is_valid(token, None)
