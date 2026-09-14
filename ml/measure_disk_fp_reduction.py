"""
[Week9 성과 지표] 디스크 오탐(false positive) 감소율 측정
- min_std_ratio 하한선 적용 전/후 공식을 같은 원본 데이터에 각각 적용해서 비교
- detected_at 기준 비교는 --full 재실행 시 덮어써져서 부정확 → 이 방식이 더 정확함
"""
import pickle
import asyncio
import asyncpg
import pandas as pd
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
DATABASE_URL = os.environ["DATABASE_URL"]


def old_is_out_of_range(series, mean, std):
    """[Week9 이전] 하한선 없는 원래 로직"""
    effective_std = std or 0
    if effective_std > 0:
        return (series - mean).abs() > 3 * effective_std
    return series != mean


def new_is_out_of_range(series, mean, std, min_std_ratio=0.05):
    """[Week9] min_std_ratio 하한선 적용 (현재 anomaly_detector.py와 동일 로직)"""
    effective_std = max(std or 0, abs(mean) * min_std_ratio)
    if effective_std > 0:
        return (series - mean).abs() > 3 * effective_std
    return series != mean


async def measure():
    with open('ml/model.pkl', 'rb') as f:
        saved = pickle.load(f)

    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch("""
        SELECT cloud, disk_avg
        FROM resource_metrics
        WHERE source = 'real' AND disk_avg IS NOT NULL
    """)
    await conn.close()

    df = pd.DataFrame([dict(r) for r in rows])

    print(f"{'클라우드':<8}{'전체건수':>8}{'적용전 오탐':>12}{'적용전 %':>10}{'적용후 오탐':>12}{'적용후 %':>10}")
    for cloud, group in df.groupby('cloud'):
        if cloud not in saved:
            print(f"[경고] {cloud} 모델 없음 - 스킵")
            continue
        mean = saved[cloud]['disk_mean']
        std = saved[cloud]['disk_std']

        old_flag = old_is_out_of_range(group['disk_avg'], mean, std)
        new_flag = new_is_out_of_range(group['disk_avg'], mean, std)

        total = len(group)
        old_pct = 100 * old_flag.sum() / total
        new_pct = 100 * new_flag.sum() / total

        print(f"{cloud:<8}{total:>8}{old_flag.sum():>12}{old_pct:>9.1f}%{new_flag.sum():>12}{new_pct:>9.1f}%")


if __name__ == "__main__":
    asyncio.run(measure())
