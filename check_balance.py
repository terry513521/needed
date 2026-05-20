#!/usr/bin/env python3

import os
import time
import json
import logging
from datetime import datetime, timezone

import requests


CHUTES_API_BASE = os.getenv("CHUTES_API_BASE", "https://api.chutes.ai")
CHUTES_API_KEY = os.getenv("CHUTES_API_KEY", "cpk_65e94b78ad664df0866d6523a66fe477.2503334190fe5d918563f570013aa8df.QoMkSfKjTYDIyJIpKo26mfqqwx1ERzZK")  # example: cpk_xxxxx
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1506672291885355138/CLAKMJft7vpJWaqzhczb6Zdz7DaOBiEswZcKryVfURZIG-DWXrdXClNsNRRI-wxcZz0S")

CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "1800"))  # 30 mins
LOW_BALANCE_THRESHOLD_USD = float(os.getenv("LOW_BALANCE_THRESHOLD_USD", "50"))
LOG_FILE = os.getenv("LOG_FILE", "chutes_balance_monitor.log")

_alert_sent_for_low_balance = False


# -------------------------
# Logging
# -------------------------

logger = logging.getLogger("chutes_balance_monitor")
logger.setLevel(logging.INFO)

formatter = logging.Formatter(
    "%(asctime)s | %(levelname)s | %(message)s"
)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)

file_handler = logging.FileHandler(LOG_FILE)
file_handler.setFormatter(formatter)

logger.handlers.clear()
logger.addHandler(console_handler)
logger.addHandler(file_handler)


# -------------------------
# Helpers
# -------------------------

def require_env():
    missing = []

    if not CHUTES_API_KEY:
        missing.append("CHUTES_API_KEY")
    if not DISCORD_WEBHOOK_URL:
        missing.append("DISCORD_WEBHOOK_URL")

    if missing:
        raise RuntimeError(f"Missing env vars: {', '.join(missing)}")


def extract_balance_usd(data):
    """
    Expected /users/me response includes:
      {
        "username": "...",
        "user_id": "...",
        "balance": 123.45,
        ...
      }
    """

    if not isinstance(data, dict):
        raise ValueError(f"Unexpected response type: {type(data)}")

    if "balance" not in data:
        raise ValueError(
            f"Could not find 'balance' field in Chutes response: {json.dumps(data)[:1500]}"
        )

    return float(data["balance"])


def get_chutes_account_info():
    url = f"{CHUTES_API_BASE.rstrip('/')}/users/me"

    headers = {
        "Authorization": f"Bearer {CHUTES_API_KEY}",
        "Accept": "application/json",
    }

    response = requests.get(url, headers=headers, timeout=30)

    if response.status_code >= 400:
        raise RuntimeError(
            f"Chutes account request failed: HTTP {response.status_code} | "
            f"{response.text[:1000]}"
        )

    data = response.json()
    balance_usd = extract_balance_usd(data)

    username = data.get("username", "unknown")
    user_id = data.get("user_id", "unknown")
    payment_address = data.get("payment_address", "unknown")

    return balance_usd, username, user_id, payment_address, data


def send_discord_message(content):
    response = requests.post(
        DISCORD_WEBHOOK_URL,
        json={"content": content},
        timeout=30,
    )

    if response.status_code >= 400:
        raise RuntimeError(
            f"Discord webhook failed: HTTP {response.status_code} | "
            f"{response.text[:1000]}"
        )


def send_low_balance_alert(balance_usd, username, user_id, payment_address):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    content = (
        "⚠️ **Chutes balance is low**\n"
        f"Time: `{now}`\n"
        f"User: `{username}`\n"
        f"User ID: `{user_id}`\n"
        f"Current balance: `${balance_usd:.2f}`\n"
        f"Threshold: `${LOW_BALANCE_THRESHOLD_USD:.2f}`\n"
        f"Top-up address: `{payment_address}`"
    )

    send_discord_message(content)


def send_error_alert(error_message):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    content = (
        "🚨 **Chutes balance monitor error**\n"
        f"Time: `{now}`\n"
        f"Error: `{error_message}`"
    )

    send_discord_message(content)


# -------------------------
# Main loop
# -------------------------

def main():
    global _alert_sent_for_low_balance

    require_env()

    logger.info("Starting Chutes balance monitor")
    logger.info("Chutes API base: %s", CHUTES_API_BASE)
    logger.info("Checking every %s seconds", CHECK_INTERVAL_SECONDS)
    logger.info("Low balance threshold: $%.2f", LOW_BALANCE_THRESHOLD_USD)
    logger.info("Log file: %s", LOG_FILE)

    while True:
        try:
            balance_usd, username, user_id, payment_address, raw_response = get_chutes_account_info()

            # Logs balance every single check.
            logger.info(
                "Chutes balance: $%.2f | user=%s | user_id=%s",
                balance_usd,
                username,
                user_id,
            )

            if balance_usd <= LOW_BALANCE_THRESHOLD_USD:
                logger.warning(
                    "Balance is below threshold: $%.2f <= $%.2f",
                    balance_usd,
                    LOW_BALANCE_THRESHOLD_USD,
                )

                if not _alert_sent_for_low_balance:
                    send_low_balance_alert(
                        balance_usd=balance_usd,
                        username=username,
                        user_id=user_id,
                        payment_address=payment_address,
                    )
                    _alert_sent_for_low_balance = True
                    logger.warning("Low balance Discord alert sent")
                else:
                    logger.info("Low balance alert already sent; skipping duplicate alert")

            else:
                logger.info(
                    "Balance is healthy: $%.2f > $%.2f",
                    balance_usd,
                    LOW_BALANCE_THRESHOLD_USD,
                )

                if _alert_sent_for_low_balance:
                    logger.info("Balance recovered above threshold; alert state reset")

                _alert_sent_for_low_balance = False

        except KeyboardInterrupt:
            logger.info("Stopped by user")
            break

        except Exception as e:
            error_message = str(e)
            logger.exception("Monitor check failed: %s", error_message)

            try:
                send_error_alert(error_message)
                logger.info("Discord error alert sent")
            except Exception as discord_error:
                logger.exception(
                    "Failed to send Discord error alert: %s",
                    str(discord_error),
                )

        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()