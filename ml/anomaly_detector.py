import os
import argparse
import pickle
import pandas as pd
import asyncpg
import asyncio
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
DATABASE_URL = os.environ["DATABASE_URL"]


def is_out_of_range(series, mean, std, min_std_ratio: float = 0.05):
    """
    평균±3표준편차를 벗어나면 True.
    [9주차] 디스크처럼 원래 거의 안 움직이는 지표는 표준편차가 평균의 1%도 안 돼서
    아주 작은 노이즈에도 3σ 기준을 넘어버림 (거의 항상 이상으로 찍히는 문제).
    그래서 표준편차가 평균의 min_std_ratio(기본 5%)보다 작으면, 그 값을 최소 폭으로 대신 써서
    "최소한 평균의 15%(3×5%)는 벗어나야 이상"이라는 하한선을 둔다.
    """
    effective_std = max(std or 0, abs(mean) * min_std_ratio)
    if effective_std > 0:
        return (series - mean).abs() > 3 * effective_std
    return series != mean


async def detect_and_save(full: bool = False):
    with open('ml/model.pkl', 'rb') as f:
        saved = pickle.load(f)  # { cloud: {'model':..., 'scaler':..., 'cpu_mean':..., 'cpu_std':..., 'mem_mean':..., 'mem_std':..., 'disk_mean':..., 'disk_std':...} }

    conn = await asyncpg.connect(DATABASE_URL)

    if full:
        rows = await conn.fetch("""
            SELECT cloud, instance_id, timestamp, cpu_avg,
                   COALESCE(memory_avg, 0) AS memory_avg,
                   COALESCE(disk_avg, 0) AS disk_avg
            FROM resource_metrics
            WHERE source = 'real'
            ORDER BY timestamp
        """)
    else:
        rows = await conn.fetch("""
            SELECT cloud, instance_id, timestamp, cpu_avg,
                   COALESCE(memory_avg, 0) AS memory_avg,
                   COALESCE(disk_avg, 0) AS disk_avg
            FROM resource_metrics
            WHERE timestamp >= NOW() - INTERVAL '1 hour'
              AND source = 'real'
            ORDER BY timestamp
        """)

    if not rows:
        print("[INFO] 대상 데이터 없음 (source='real')")
        await conn.close()
        return

    df = pd.DataFrame([dict(r) for r in rows])
    features = ['cpu_avg', 'memory_avg', 'disk_avg']
    total, total_anomaly = 0, 0

    for cloud, group in df.groupby('cloud'):
        if cloud not in saved:
            print(f"[경고] {cloud}용 학습된 모델이 없음 - 스킵")
            continue

        model = saved[cloud]['model']
        scaler = saved[cloud]['scaler']

        X = group[features].fillna(0)
        X_scaled = scaler.transform(X)

        # score는 계속 참고 지표로 저장 (3개 지표를 다 반영한 IsolationForest 점수)
        scores = model.score_samples(X_scaled)

        group = group.copy()
        group['score'] = scores

        # [9주차] CPU/메모리/디스크 각각 독립적으로 평균±3σ 판정
        # -> Grafana에서 패널별로 "그 지표 자체가 이상이었는지"를 바로 필터링할 수 있게
        cpu_out = is_out_of_range(group['cpu_avg'], saved[cloud]['cpu_mean'], saved[cloud]['cpu_std'])
        mem_out = is_out_of_range(group['memory_avg'], saved[cloud]['mem_mean'], saved[cloud]['mem_std'])
        disk_out = is_out_of_range(group['disk_avg'], saved[cloud]['disk_mean'], saved[cloud]['disk_std'])

        group['cpu_anomaly'] = cpu_out
        group['mem_anomaly'] = mem_out
        group['disk_anomaly'] = disk_out
        group['anomaly'] = cpu_out | mem_out | disk_out  # 종합 판정 (요약용, 셋 중 하나라도 이상)

        for _, row in group.iterrows():
            await conn.execute("""
                INSERT INTO anomaly_results
                    (cloud, instance_id, timestamp, cpu_avg, memory_avg, disk_avg,
                     anomaly, cpu_anomaly, mem_anomaly, disk_anomaly, score)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                ON CONFLICT (cloud, instance_id, timestamp)
                DO UPDATE SET cpu_avg = EXCLUDED.cpu_avg,
                              memory_avg = EXCLUDED.memory_avg,
                              disk_avg = EXCLUDED.disk_avg,
                              anomaly = EXCLUDED.anomaly,
                              cpu_anomaly = EXCLUDED.cpu_anomaly,
                              mem_anomaly = EXCLUDED.mem_anomaly,
                              disk_anomaly = EXCLUDED.disk_anomaly,
                              score = EXCLUDED.score,
                              detected_at = now()
            """, row['cloud'], row['instance_id'], row['timestamp'],
                 row['cpu_avg'], row['memory_avg'], row['disk_avg'],
                 bool(row['anomaly']), bool(row['cpu_anomaly']),
                 bool(row['mem_anomaly']), bool(row['disk_anomaly']),
                 float(row['score']))

        anomaly_count = int(group['anomaly'].sum())
        total += len(group)
        total_anomaly += anomaly_count
        print(f"[{cloud}] 전체 {len(group)}건 중 이상 {anomaly_count}건 "
              f"(CPU 이상 {int(cpu_out.sum())}건 / 메모리 이상 {int(mem_out.sum())}건 / 디스크 이상 {int(disk_out.sum())}건)")

    print(f"[OK] 탐지 완료 - 전체 {total}건 중 이상 {total_anomaly}건")
    await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="이상탐지 실행")
    parser.add_argument("--full", action="store_true",
                         help="최근 1시간이 아닌 전체 real 데이터 재계산")
    args = parser.parse_args()
    asyncio.run(detect_and_save(full=args.full))
