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

MAD_WINDOW_DAYS = 7
MAD_THRESHOLD = 3.5


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


def is_out_of_range_mad(series, median, mad, threshold: float = MAD_THRESHOLD, min_mad_ratio: float = 0.05):
    """
    [median/MAD 실험, 2026-09-27 도입] modified z-score 기반 판정.
    modified_z = 0.6745 * (x - median) / MAD  (Iglewicz & Hoaglin 권장 공식, 임계값 3.5)

    is_out_of_range()(평균/표준편차 방식)의 약점: 이상치 자체가 평균과 표준편차를 같이
    끌어올려서, 진짜 이상치가 다음번엔 "정상 범위 안"으로 둔갑할 수 있음 (masking).
    median/MAD는 극단값 몇 개로는 거의 안 흔들려서 이상치에 훨씬 강하다.

    디스크처럼 거의 안 움직이는 지표에 대한 안전장치는 is_out_of_range()와 같은 이유로 유지.
    """
    effective_mad = max(mad or 0, abs(median) * min_mad_ratio)
    if effective_mad > 0:
        modified_z = 0.6745 * (series - median) / effective_mad
        return modified_z.abs() > threshold
    return series != median


async def fetch_rolling_baseline(conn, cloud: str, window_days: int = MAD_WINDOW_DAYS):
    """
    [median/MAD 실험] train.py가 주 1회 계산해서 model.pkl에 고정해두는 평균/표준편차와 달리,
    이 baseline은 매 실행마다 최근 window_days(기본 7일)치 실제 데이터로 새로 계산한다.
    -> 재학습 주기(매주 1회)를 기다리지 않고 최근 추세 변화를 더 빨리 반영 (rolling window).

    주의: --full로 과거 데이터 전체를 재계산할 때도 baseline은 항상 "지금 시점 기준 최근 7일"
    하나만 쓴다. 각 행의 타임스탬프 시점에 맞춰 baseline을 다시 구하는 건 아니라서,
    오래된 과거 데이터에 대한 --full 결과는 참고용으로만 보는 게 맞다.
    """
    rows = await conn.fetch(f"""
        SELECT cpu_avg, COALESCE(memory_avg, 0) AS memory_avg, COALESCE(disk_avg, 0) AS disk_avg
        FROM resource_metrics
        WHERE cloud = $1
          AND source = 'real'
          AND timestamp >= NOW() - INTERVAL '{window_days} days'
    """, cloud)

    if not rows:
        return None

    df = pd.DataFrame([dict(r) for r in rows])
    baseline = {}
    for feature in ['cpu_avg', 'memory_avg', 'disk_avg']:
        median = df[feature].median()
        mad = (df[feature] - median).abs().median()
        baseline[feature] = {'median': median, 'mad': mad}
    return baseline


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
        cpu_out = is_out_of_range(group['cpu_avg'], saved[cloud]['cpu_mean'], saved[cloud]['cpu_std'])
        mem_out = is_out_of_range(group['memory_avg'], saved[cloud]['mem_mean'], saved[cloud]['mem_std'])
        disk_out = is_out_of_range(group['disk_avg'], saved[cloud]['disk_mean'], saved[cloud]['disk_std'])

        group['cpu_anomaly'] = cpu_out
        group['mem_anomaly'] = mem_out
        group['disk_anomaly'] = disk_out
        group['anomaly'] = cpu_out | mem_out | disk_out  # 종합 판정 (요약용, 셋 중 하나라도 이상)

        # [median/MAD 실험] 같은 데이터에 robust 통계 방식을 나란히 적용해서 비교
        baseline = await fetch_rolling_baseline(conn, cloud)
        if baseline is None:
            print(f"[경고] {cloud} rolling baseline 계산할 데이터 없음 - MAD 판정 전부 정상 처리")
            cpu_out_mad = pd.Series(False, index=group.index)
            mem_out_mad = pd.Series(False, index=group.index)
            disk_out_mad = pd.Series(False, index=group.index)
        else:
            cpu_out_mad = is_out_of_range_mad(group['cpu_avg'], baseline['cpu_avg']['median'], baseline['cpu_avg']['mad'])
            mem_out_mad = is_out_of_range_mad(group['memory_avg'], baseline['memory_avg']['median'], baseline['memory_avg']['mad'])
            disk_out_mad = is_out_of_range_mad(group['disk_avg'], baseline['disk_avg']['median'], baseline['disk_avg']['mad'])

        group['cpu_anomaly_mad'] = cpu_out_mad
        group['mem_anomaly_mad'] = mem_out_mad
        group['disk_anomaly_mad'] = disk_out_mad
        group['anomaly_mad'] = cpu_out_mad | mem_out_mad | disk_out_mad

        for _, row in group.iterrows():
            await conn.execute("""
                INSERT INTO anomaly_results
                    (cloud, instance_id, timestamp, cpu_avg, memory_avg, disk_avg,
                     anomaly, cpu_anomaly, mem_anomaly, disk_anomaly, score,
                     anomaly_mad, cpu_anomaly_mad, mem_anomaly_mad, disk_anomaly_mad)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
                ON CONFLICT (cloud, instance_id, timestamp)
                DO UPDATE SET cpu_avg = EXCLUDED.cpu_avg,
                              memory_avg = EXCLUDED.memory_avg,
                              disk_avg = EXCLUDED.disk_avg,
                              anomaly = EXCLUDED.anomaly,
                              cpu_anomaly = EXCLUDED.cpu_anomaly,
                              mem_anomaly = EXCLUDED.mem_anomaly,
                              disk_anomaly = EXCLUDED.disk_anomaly,
                              score = EXCLUDED.score,
                              anomaly_mad = EXCLUDED.anomaly_mad,
                              cpu_anomaly_mad = EXCLUDED.cpu_anomaly_mad,
                              mem_anomaly_mad = EXCLUDED.mem_anomaly_mad,
                              disk_anomaly_mad = EXCLUDED.disk_anomaly_mad,
                              detected_at = now()
            """, row['cloud'], row['instance_id'], row['timestamp'],
                 row['cpu_avg'], row['memory_avg'], row['disk_avg'],
                 bool(row['anomaly']), bool(row['cpu_anomaly']),
                 bool(row['mem_anomaly']), bool(row['disk_anomaly']),
                 float(row['score']),
                 bool(row['anomaly_mad']), bool(row['cpu_anomaly_mad']),
                 bool(row['mem_anomaly_mad']), bool(row['disk_anomaly_mad']))

        anomaly_count = int(group['anomaly'].sum())
        anomaly_mad_count = int(group['anomaly_mad'].sum())
        both_count = int((group['anomaly'] & group['anomaly_mad']).sum())
        sigma_only_count = int((group['anomaly'] & ~group['anomaly_mad']).sum())
        mad_only_count = int((~group['anomaly'] & group['anomaly_mad']).sum())

        total += len(group)
        total_anomaly += anomaly_count
        print(f"[{cloud}] 전체 {len(group)}건 중 3σ 이상 {anomaly_count}건 / MAD 이상 {anomaly_mad_count}건 "
              f"(둘 다 {both_count}건 / 3σ만 {sigma_only_count}건 / MAD만 {mad_only_count}건)")

    print(f"[OK] 탐지 완료 - 전체 {total}건 중 3σ 기준 이상 {total_anomaly}건")
    await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="이상탐지 실행")
    parser.add_argument("--full", action="store_true",
                         help="최근 1시간이 아닌 전체 real 데이터 재계산")
    args = parser.parse_args()
    asyncio.run(detect_and_save(full=args.full))
