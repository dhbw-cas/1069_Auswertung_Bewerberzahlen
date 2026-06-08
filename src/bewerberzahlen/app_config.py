from __future__ import annotations

import os

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError


def get_config_value(name: str) -> str | None:
    env_value = os.environ.get(name)
    if env_value:
        return env_value
    try:
        secret_value = st.secrets.get(name)
    except (FileNotFoundError, KeyError, StreamlitSecretNotFoundError):
        return None
    if not secret_value:
        return None
    return str(secret_value)


def get_database_url() -> str | None:
    return get_config_value("DATABASE_URL")
