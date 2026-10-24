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
from pathlib import Path
from dotenv import load_dotenv

from notifier import send_slack_alert

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
DATABASE_URL = os.environ["DATABASE_URL"]

# 클라우드별 월 예산 (USD)은 .env의 BUDGET_AWS / BUDGET_AZURE / BUDGET_GCP에서 읽는다.
# 설정하지 않은 클라우드는 예산 검사를 건너뛴다 (decisions/0011 참고, 0015 단계 1).


def monthly_budget(cloud: str):
    raw = os.environ.get(f"BUDGET_{cloud.upper()}", "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        raise SystemExit(f"[설정 오류] BUDGET_{cloud.upper()} 값이 숫자가 아닙니다: {raw!r}")


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
        budget = monthly_budget(cloud)
        if budget is None:
            print(f"[SKIP] {cloud} ${total:.2f} - 예산 미설정 (BUDGET_{cloud.upper()})")
        elif total > budget:
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
