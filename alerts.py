"""
alerts.py — уведомление в Telegram о сбое часового запуска.

Без ALERT_BOT_TOKEN / ALERT_CHAT_IDS уведомления выключены (только лог).
Сбой отправки никогда не поднимает исключение: он не должен скрыть
исходную ошибку, из-за которой уведомление и отправлялось.
"""

import logging

import requests

from config import (ALERT_BOT_TOKEN, ALERT_CHAT_IDS, AMO_TOKEN, META_TOKEN,
                    GOOGLE_SERVICE_ACCOUNT_JSON)

logger = logging.getLogger("jarvis_sheet.alerts")

TELEGRAM_LIMIT = 4000   # сообщение Telegram — до 4096 символов


def mask_secrets(text: str) -> str:
    """Убирает из текста токены и ключ Google, если они туда попали."""
    text = str(text)
    for secret in (AMO_TOKEN, META_TOKEN, ALERT_BOT_TOKEN, GOOGLE_SERVICE_ACCOUNT_JSON):
        if secret and len(secret) >= 8:
            text = text.replace(secret, "***")
    return text


def send_alert(text: str) -> bool:
    """Шлёт text всем ALERT_CHAT_IDS. -> True, если ушло хотя бы одно сообщение."""
    text = mask_secrets(text)[:TELEGRAM_LIMIT]
    if not ALERT_BOT_TOKEN or not ALERT_CHAT_IDS:
        logger.warning("Уведомления выключены (нет ALERT_BOT_TOKEN / ALERT_CHAT_IDS): %s", text)
        return False
    url = f"https://api.telegram.org/bot{ALERT_BOT_TOKEN}/sendMessage"
    sent = False
    for chat_id in ALERT_CHAT_IDS:
        try:
            r = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=15)
        except requests.RequestException as e:
            # в тексте исключения requests есть URL, а в нём токен бота
            logger.error("Telegram: не отправлено в %s: %s", chat_id, mask_secrets(type(e).__name__))
            continue
        if r.status_code == 200:
            sent = True
        else:
            logger.error("Telegram: не отправлено в %s: HTTP %s %s",
                         chat_id, r.status_code, mask_secrets(r.text[:200]))
    return sent
