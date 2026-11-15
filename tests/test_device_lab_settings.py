"""Comprobar que el nuevo canal queda apagado por defecto y cerrado en producción."""
import pytest
import os
from unittest.mock import patch
from pydantic import ValidationError

from app.config.settings import Settings
from app.device_channel.authenticated_lab import encoded


GOOD_KEY = encoded(bytes(range(32)))


def test_disabled_by_default():
    with patch.dict(os.environ, {}, clear=True):
        s = Settings(_env_file=None)
        assert s.device_lab_enabled is False
        assert s.device_lab_key.get_secret_value() == ""


def test_enabled_only_with_private_secret_and_no_guest_simulator():
    with patch.dict(os.environ, {}, clear=True):
        s = Settings(_env_file=None, device_lab_enabled=True, device_lab_key=GOOD_KEY)
        assert s.device_lab_enabled is True
        assert GOOD_KEY not in repr(s)
    for overrides in (
        {"app_env":"production"},
        {"device_lab_key":""},
        {"device_lab_key":"not_base64url"},
        {"device_lab_enabled":"yes"},
    ):
        with patch.dict(os.environ, {}, clear=True), pytest.raises(ValidationError):
            Settings(_env_file=None, **({"device_lab_enabled": True, "device_lab_key": GOOD_KEY} | overrides))
