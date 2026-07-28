import os
from dotenv import load_dotenv
from snaptrade_client import SnapTrade

load_dotenv()

CLIENT_ID = os.getenv("SNAPTRADE_CLIENT_ID")
CONSUMER_KEY = os.getenv("SNAPTRADE_CONSUMER_KEY")
USER_ID = os.getenv("SNAPTRADE_USER_ID")
USER_SECRET = os.getenv("SNAPTRADE_USER_SECRET")

# Initialize with environment variables
snaptrade = SnapTrade(
    client_id=os.getenv("SNAPTRADE_CLIENT_ID"),
    consumer_key=os.getenv("SNAPTRADE_CONSUMER_KEY")
)

async def fetch_all_user_positions():
    """
    Fetches raw stock positions and options positions for Personal API keys.
    Runs SDK calls in an async thread to prevent blocking FastAPI's event loop.
    """
    def _get_data():
        # 1. Fetch connected accounts
        accounts_res = snaptrade.account_information.list_user_accounts(
            user_id=None,
            user_secret=None
        )
        accounts = accounts_res.body or []

        all_equities = []
        all_options = []

        # 2. Iterate through accounts to pull holdings and option positions
        for acc in accounts:
            acc_id = acc.get("id")
            if not acc_id:
                continue

            # Fetch equity positions
            pos_res = snaptrade.account_information.get_user_account_positions(
                user_id=None,
                user_secret=None,
                account_id=acc_id
            )
            if pos_res.body:
                all_equities.extend(pos_res.body)

            # Fetch option holdings
            opt_res = snaptrade.options.list_option_holdings(
                user_id=None,
                user_secret=None,
                account_id=acc_id
            )
            if opt_res.body:
                all_options.extend(opt_res.body)

        return all_equities, all_options

    # Run blocking SDK HTTP calls in threadpool so 'await' works in FastAPI
    return await asyncio.to_thread(_get_data)

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

async def fetch_raw_account_data(account_id: str):
    """
    Fetches raw stock positions and option holdings using SnapTrade's SDK,
    converting SDK model objects to pure Python dictionaries.
    """
    # 1. Fetch equity positions
    equities_res = snaptrade.account_information.get_user_account_positions(
        user_id=USER_ID,
        user_secret=USER_SECRET,
        account_id=account_id
    )

    # 2. Fetch option holdings
    options_res = snaptrade.options.list_option_holdings(
        user_id=USER_ID,
        user_secret=USER_SECRET,
        account_id=account_id
    )

    # Clean SDK response objects into plain Python lists of dicts
    raw_equities = _clean_sdk_response(equities_res)
    raw_options = _clean_sdk_response(options_res)

    return raw_equities, raw_options

# app/services/snaptrade.py

async def fetch_all_user_positions():
    # 1. Fetch all accounts attached to the user
    accounts_res = snaptrade.account_information.list_user_accounts(
        user_id=USER_ID,
        user_secret=USER_SECRET
    )
    accounts = _clean_sdk_response(accounts_res)

    all_equities = []
    all_options = []

    # 2. Extract positions for each valid account ID
    for acc in accounts:
        # Accounts returned by list_user_accounts are dicts containing 'id'
        acc_id = acc.get("id") if isinstance(acc, dict) else getattr(acc, "id", None)
        if not acc_id:
            continue

        try:
            eq_res = snaptrade.account_information.get_user_account_positions(
                user_id=USER_ID, user_secret=USER_SECRET, account_id=acc_id
            )
            opt_res = snaptrade.options.list_option_holdings(
                user_id=USER_ID, user_secret=USER_SECRET, account_id=acc_id
            )

            all_equities.extend(_clean_sdk_response(eq_res))
            all_options.extend(_clean_sdk_response(opt_res))
        except Exception as e:
            # Prevent a failure on a single closed/unsupported account from breaking the API call
            continue

    return all_equities, all_options