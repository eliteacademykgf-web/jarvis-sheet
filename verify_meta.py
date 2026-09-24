"""
verify_meta.py — проверка get_daily_ad_stats на реальных данных.

Берёт последние 7 полных дней (вчера и 6 дней до него; сегодня не
берём — день не закончился), вызывает get_daily_ad_stats на каждый
и печатает строки по дням, число объявлений, сумму расхода и дни
с нулевым расходом или ошибкой. Для ручной сверки с Ads Manager.

Запуск: python verify_meta.py
"""

import logging
from datetime import date, timedelta

from config import META_TOKEN, AD_ACCOUNT_ID
from meta_client import GRAPH_API_VERSION, MetaAPIError, get_daily_ad_stats

DAYS = 7


def main():
    logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s",
                        level=logging.WARNING)
    if not META_TOKEN or not AD_ACCOUNT_ID:
        raise SystemExit("Нужны META_TOKEN и AD_ACCOUNT_ID в .env или окружении")

    yesterday = date.today() - timedelta(days=1)
    days = [yesterday - timedelta(days=i) for i in range(DAYS - 1, -1, -1)]
    print(f"Graph API {GRAPH_API_VERSION}, аккаунт {AD_ACCOUNT_ID}, "
          f"{days[0]} — {days[-1]}\n")
    print(f"{'дата':<12}{'строк':>7}{'расход':>11}{'показы':>10}"
          f"{'клики':>8}{'dm_leads':>10}{'site_leads':>12}")

    all_rows, zero_days, error_days = [], [], []
    for d in days:
        try:
            rows = get_daily_ad_stats(AD_ACCOUNT_ID, d, META_TOKEN)
        except MetaAPIError as e:
            error_days.append((d, str(e)))
            print(f"{d.isoformat():<12}  ОШИБКА: {e}")
            continue
        all_rows.extend(rows)
        spend = sum(r["spend"] for r in rows)
        if spend == 0:
            zero_days.append(d)
        print(f"{d.isoformat():<12}{len(rows):>7}{spend:>11.2f}"
              f"{sum(r['impressions'] for r in rows):>10}"
              f"{sum(r['clicks'] for r in rows):>8}"
              f"{sum(r['dm_leads'] for r in rows):>10}"
              f"{sum(r['site_leads'] for r in rows):>12}")

    print(f"\nВсего строк (объявление × день): {len(all_rows)}")
    print(f"Объявлений за {DAYS} дней:          {len({r['ad_id'] for r in all_rows})}")
    print(f"Расход за {DAYS} дней:              {sum(r['spend'] for r in all_rows):.2f}")
    print(f"Дни с расходом 0:               "
          f"{', '.join(d.isoformat() for d in zero_days) or 'нет'}")
    print(f"Дни с ошибкой запроса:          "
          f"{', '.join(d.isoformat() for d, _ in error_days) or 'нет'}")


if __name__ == "__main__":
    main()
