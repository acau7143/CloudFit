"""
클라우드별 월 예산 초과 확인 및 Slack 알림 (9주차)
- cost_records를 이번 달 데이터 기준으로 합산해서 예산과 비교한다.
- 별도 저장 테이블 없이 매번 실시간 계산한다.
"""
import argparse
import asyncio
import os
from datetime import date

import asyncpg

from notifier import send_slack_alert

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://finops:finops123@localhost:5432/finops_db",
)

# 클라우드별 월 예산 (USD) - 잠정값, 팀 확정 필요 (decisions/0011 참고)
MONTHLY_BUDGET = {
    "AWS": 50.0,
    "Azure": 50.0,
    "GCP": 50.0,
}


async def check_budget(dry_run: bool = False):
    conn = await asyncpg.connect(DATABASE_URL)
    today = date.today()
    month_start = today.replace(day=1)

    rows = await conn.fetch("""
        SELECT cloud, SUM(cost_usd) AS total
        FROM cost_records
        WHERE date >= $1
        GROUP BY cloud
    """, month_start)

    for row in rows:
        cloud, total = row['cloud'], row['total']
        budget = MONTHLY_BUDGET.get(cloud)
        if budget and total > budget:
            msg = f"{cloud} 이번 달 누적 비용 ${total:.2f}이 예산 ${budget:.2f}를 초과했습니다."
            print(f"[경고] {msg}")
            if not dry_run:
                send_slack_alert(f"[예산 초과] {cloud}", msg)
        else:
            print(f"[OK] {cloud} ${total:.2f} / ${budget:.2f}")

    await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(check_budget(dry_run=args.dry_run))
