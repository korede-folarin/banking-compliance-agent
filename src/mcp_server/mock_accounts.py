import json

from src.config import MOCK_ACCOUNTS_PATH


def _load_accounts() -> list[dict]:
    with open(MOCK_ACCOUNTS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data["accounts"]


_ACCOUNTS = _load_accounts()


def lookup_account(name_or_id: str) -> dict | None:
    """Look up a mock account by account_id or account_holder_name (case-insensitive, exact match)."""
    query = name_or_id.strip().lower()
    for account in _ACCOUNTS:
        if account["account_id"].lower() == query or account["account_holder_name"].lower() == query:
            return account
    return None
