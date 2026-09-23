from __future__ import annotations

from pathlib import Path

from auth import prompt_create_credentials

PROJECT_DIR = Path(__file__).resolve().parent
ENV_FILE = PROJECT_DIR / ".env"
ENV_EXAMPLE = PROJECT_DIR / ".env.example"


def load_env_text() -> str:
    if ENV_FILE.exists():
        return ENV_FILE.read_text(encoding="utf-8")
    if ENV_EXAMPLE.exists():
        return ENV_EXAMPLE.read_text(encoding="utf-8")
    return ""


def set_env_value(text: str, key: str, value: str) -> str:
    lines = text.splitlines()
    prefix = key + "="
    replaced = False
    output = []
    for line in lines:
        if line.startswith(prefix):
            output.append(prefix + value)
            replaced = True
        else:
            output.append(line)
    if not replaced:
        output.append(prefix + value)
    return "\n".join(output) + "\n"


def main() -> int:
    print("\nSimple local login setup")
    print("Your password will be stored only as a salted PBKDF2 hash in .env.\n")
    try:
        username, password_hash = prompt_create_credentials()
        text = load_env_text()
        text = set_env_value(text, "LOGIN_ENABLED", "true")
        text = set_env_value(text, "LOGIN_USERNAME", username)
        text = set_env_value(text, "LOGIN_PASSWORD_HASH", password_hash)
        ENV_FILE.write_text(text, encoding="utf-8")
        print(f"\nLogin configured successfully in: {ENV_FILE}")
        print("You can now run: python job_tracker.py --once")
        return 0
    except (KeyboardInterrupt, EOFError):
        print("\nSetup cancelled.")
        return 1
    except ValueError as exc:
        print(f"Setup failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
