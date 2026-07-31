import os
import asyncio
import json
import logging
from dotenv import load_dotenv
import snaptrade_client
from snaptrade_client import SnapTrade

load_dotenv()

logger = logging.getLogger(__name__)

USER_ID = os.getenv("SNAPTRADE_USER_ID")
USER_SECRET = os.getenv("SNAPTRADE_USER_SECRET")

snaptrade = SnapTrade(
    client_id=os.getenv("SNAPTRADE_CLIENT_ID"),
    consumer_key=os.getenv("SNAPTRADE_CONSUMER_KEY")
)

def _clean_sdk_response(res):
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
    Fetches stock positions, options holdings, account balances, and account metadata.
    Returns: (all_equities, all_options, all_balances, accounts)
    """
    def _sync_fetch():
        accounts_res = snaptrade.account_information.list_user_accounts(
            user_id=USER_ID,
            user_secret=USER_SECRET
        )
        accounts = _clean_sdk_response(accounts_res)

        all_equities = []
        all_options = []
        all_balances = []

        for acc in accounts:
            acc_id = acc.get("id") if isinstance(acc, dict) else getattr(acc, "id", None)
            if not acc_id:
                continue

            try:
                # 1. Fetch Positions
                eq_res = snaptrade.account_information.get_user_account_positions(
                    user_id=USER_ID, user_secret=USER_SECRET, account_id=acc_id
                )
                cleaned_eq = _clean_sdk_response(eq_res)
                
                for item in cleaned_eq:
                    if isinstance(item, dict):
                        item["account_id"] = acc_id
                        
                        # -------------------------------------------------------------
                        # FIX: Filter out options from equities list to prevent duplicate 
                        # accounting of options/collateral in portfolio totals.
                        # -------------------------------------------------------------
                        symbol_info = item.get("symbol", {})
                        if isinstance(symbol_info, dict) and "option_symbol" in symbol_info:
                            continue  # Skip option contracts here; list_option_holdings handles them
                            
                        all_equities.append(item)

                # 2. Fetch Options
                opt_res = snaptrade.options.list_option_holdings(
                    user_id=USER_ID, user_secret=USER_SECRET, account_id=acc_id
                )
                cleaned_opt = _clean_sdk_response(opt_res)
                for item in cleaned_opt:
                    if isinstance(item, dict):
                        item["account_id"] = acc_id
                all_options.extend(cleaned_opt)

                # 3. Fetch Balances
                bal_res = snaptrade.account_information.get_user_account_balance(
                    user_id=USER_ID, user_secret=USER_SECRET, account_id=acc_id
                )
                cleaned_bal = _clean_sdk_response(bal_res)
                logger.warning(
                    "SNAPTRADE RAW BALANCE account_id=%s payload=%s",
                    acc_id,
                    json.dumps(cleaned_bal, default=str, sort_keys=True),
                )
                if isinstance(cleaned_bal, list):
                    for item in cleaned_bal:
                        if isinstance(item, dict):
                            # SnapTrade balance rows omit their parent account, so
                            # retain the account used to fetch them for broker mapping.
                            item["account_id"] = acc_id
                    all_balances.extend(cleaned_bal)
                elif isinstance(cleaned_bal, dict):
                    cleaned_bal["account_id"] = acc_id
                    all_balances.append(cleaned_bal)

            except Exception as e:
                print(f"Error fetching account {acc_id}: {e}")
                continue

        return all_equities, all_options, all_balances, accounts

    return await asyncio.to_thread(_sync_fetch)
