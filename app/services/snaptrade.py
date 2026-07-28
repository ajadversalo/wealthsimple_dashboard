import os
import asyncio
from dotenv import load_dotenv
from snaptrade_client import SnapTrade

load_dotenv()

CLIENT_ID = os.getenv("SNAPTRADE_CLIENT_ID", "PERS-N918HEG1FCVRF14XCB37")
CONSUMER_KEY = os.getenv("SNAPTRADE_CONSUMER_KEY", "teViF6Sp7S1q9snJRUCy4Qrri2iAI1ixXYiIUDZ6hDMQSzuhVE")

# Load credentials from ENV. For Personal Keys, if they are not set, leave them empty/None
USER_ID = os.getenv("SNAPTRADE_USER_ID")
USER_SECRET = os.getenv("SNAPTRADE_USER_SECRET")

snaptrade = SnapTrade(
    client_id=CLIENT_ID,
    consumer_key=CONSUMER_KEY
)

def _get_auth_kwargs():
    """Only pass user credentials if valid, non-placeholder keys are present."""
    if USER_ID and USER_SECRET and USER_ID != "personal_account":
        return {"user_id": USER_ID, "user_secret": USER_SECRET}
    # For Personal Keys without explicit user credentials, pass empty strings or omit
    return {"user_id": "", "user_secret": ""}

def _clean_sdk_response(res):
    """Converts SDK response objects or lists into standard Python dicts."""
    if hasattr(res, "body"):
        res = res.body
    if isinstance(res, list):
        cleaned = []
        for item in res:
            if hasattr(item, "to_dict"):
                cleaned.append(item.to_dict())
            elif isinstance(item, dict):
                cleaned.append(item)
            else:
                cleaned.append(getattr(item, "__dict__", {}))
        return cleaned
    if hasattr(res, "to_dict"):
        return res.to_dict()
    return res if isinstance(res, dict) else {}

async def fetch_all_user_positions():
    """
    Fetches stock positions and option holdings using non-blocking threadpool.
    """
    def _sync_fetch():
        auth = _get_auth_kwargs()

        # 1. Fetch all accounts
        accounts_res = snaptrade.account_information.list_user_accounts(**auth)
        accounts = _clean_sdk_response(accounts_res)

        all_equities = []
        all_options = []

        # 2. Extract positions for each account
        for acc in accounts:
            acc_id = acc.get("id") if isinstance(acc, dict) else getattr(acc, "id", None)
            if not acc_id:
                continue

            try:
                eq_res = snaptrade.account_information.get_user_account_positions(
                    account_id=acc_id, **auth
                )
                opt_res = snaptrade.options.list_option_holdings(
                    account_id=acc_id, **auth
                )

                all_equities.extend(_clean_sdk_response(eq_res))
                all_options.extend(_clean_sdk_response(opt_res))
            except Exception:
                continue

        return all_equities, all_options

    # Offload synchronous SDK HTTP calls to a background thread
    return await asyncio.to_thread(_sync_fetch)