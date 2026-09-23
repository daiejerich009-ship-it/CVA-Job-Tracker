"""Simple local login protection for the job tracker.

The password is never stored in plaintext. setup_login.py creates a salted
PBKDF2-SHA256 hash which is stored in .env.
"""
from __future__ import annotations

import getpass
import hashlib
import hmac
import os
import secrets


PBKDF2_ITERATIONS = 310_000


def make_password_hash(password: str) -> str:
    if not password:
        raise ValueError("Password cannot be empty.")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS
    ).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt, expected = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations)
        ).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def login_enabled() -> bool:
    return os.getenv("LOGIN_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}


def authenticate(max_attempts: int = 3) -> bool:
    if not login_enabled():
        return True

    username = os.getenv("LOGIN_USERNAME", "").strip()
    password_hash = os.getenv("LOGIN_PASSWORD_HASH", "").strip()

    if not username or not password_hash:
        raise RuntimeError(
            "Login is enabled but credentials are not configured. "
            "Run: python setup_login.py"
        )

    print("\n=== Job Tracker Login ===")
    for attempt in range(1, max_attempts + 1):
        entered_username = input("Username: ").strip()
        entered_password = getpass.getpass("Password: ")
        if hmac.compare_digest(entered_username, username) and verify_password(entered_password, password_hash):
            print("Login successful.\n")
            return True
        remaining = max_attempts - attempt
        if remaining:
            print(f"Invalid username or password. Attempts remaining: {remaining}")

    print("Too many failed login attempts. Exiting.")
    return False


def prompt_create_credentials() -> tuple[str, str]:
    username = input("Create username: ").strip()
    if not username:
        raise ValueError("Username cannot be empty.")
    password = getpass.getpass("Create password: ")
    confirm = getpass.getpass("Confirm password: ")
    if not password:
        raise ValueError("Password cannot be empty.")
    if password != confirm:
        raise ValueError("Passwords do not match.")
    return username, make_password_hash(password)
