import os
import asyncio
from dotenv import load_dotenv
from snaptrade_client import SnapTrade

load_dotenv()

# Initialize SnapTrade with Personal credentials
snaptrade = SnapTrade(
    client_id=os.getenv("SNAPTRADE_CLIENT_ID", "PERS-N918HEG1FCVRF14XCB37"),
    consumer_key=os.getenv("SNAPTRADE_CONSUMER_KEY")
)

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
    Fetches stock positions and options holdings for Personal API Keys.
    Runs SDK calls synchronously in a background thread.
    """
    def _sync_fetch():
        # Notice: NO user_id or user_secret passed here for Personal Keys
        accounts_res = snaptrade.account_information.list_user_accounts()
        accounts = _clean_sdk_response(accounts_res)

        all_equities = []
        all_options = []

        for acc in accounts:
            acc_id = acc.get("id") if isinstance(acc, dict) else getattr(acc, "id", None)
            if not acc_id:
                continue

            try:
                # Omit user_id and user_secret here as well
                eq_res = snaptrade.account_information.get_user_account_positions(
                    account_id=acc_id
                )
                opt_res = snaptrade.options.list_option_holdings(
                    account_id=acc_id
                )

                all_equities.extend(_clean_sdk_response(eq_res))
                all_options.extend(_clean_sdk_response(opt_res))
            except Exception as e:
                print(f"Error fetching account {acc_id}: {e}")
                continue

        return all_equities, all_options

    # Offload blocking SDK call to background thread so FastAPI handles it asynchronously
    return await asyncio.to_thread(_sync_fetch)