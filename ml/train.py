import os
import pandas as pd
import pickle
import asyncpg
import asyncio
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
DATABASE_URL = os.environ["DATABASE_URL"]


async def fetch_training_data():
    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch("""
        SELECT cloud, cpu_avg, COALESCE(memory_avg, 0) AS memory_avg,
               COALESCE(disk_avg, 0) AS disk_avg, timestamp
        FROM resource_metrics
        WHERE cpu_avg IS NOT NULL
          AND source = 'real'
          AND timestamp >= NOW() - INTERVAL '7 days'
        ORDER BY timestamp
    """)
    await conn.close()
    return pd.DataFrame([dict(r) for r in rows])


def train_model_for_cloud(df_cloud, cloud):
    features = ['cpu_avg', 'memory_avg', 'disk_avg']
    X = df_cloud[features].fillna(0)
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    model = IsolationForest(contamination=0.05, random_state=42, n_estimators=100)
    model.fit(X_scaled)

    cpu_mean = float(df_cloud['cpu_avg'].mean())
    cpu_std = float(df_cloud['cpu_avg'].std())
    # [8주차] memory/disk도 CPU와 동일한 방식으로 평균·표준편차 계산
    # -> anomaly_detector.py에서 CPU뿐 아니라 memory/disk 이상도 잡을 수 있게 하기 위함
    mem_mean = float(df_cloud['memory_avg'].mean())
    mem_std = float(df_cloud['memory_avg'].std())
    disk_mean = float(df_cloud['disk_avg'].mean())
    disk_std = float(df_cloud['disk_avg'].std())

    print(f"[OK] {cloud} 모델 학습 완료 - 학습 데이터: {len(df_cloud)}건 "
          f"(cpu 평균={cpu_mean:.2f}±{cpu_std:.2f}, "
          f"mem 평균={mem_mean:.2f}±{mem_std:.2f}, "
          f"disk 평균={disk_mean:.2f}±{disk_std:.2f})")

    return {
        'model': model,
        'scaler': scaler,
        'cpu_mean': cpu_mean,
        'cpu_std': cpu_std,
        'mem_mean': mem_mean,
        'mem_std': mem_std,
        'disk_mean': disk_mean,
        'disk_std': disk_std,
    }


def train_all(df):
    saved = {}
    for cloud, group in df.groupby('cloud'):
        if len(group) < 20:
            print(f"[경고] {cloud} 데이터가 {len(group)}건뿐 - 학습 스킵")
            continue
        saved[cloud] = train_model_for_cloud(group, cloud)

    with open('ml/model.pkl', 'wb') as f:
        pickle.dump(saved, f)
    print(f"[OK] 전체 저장 완료 - 클라우드: {list(saved.keys())}")
    return saved


if __name__ == "__main__":
    df = asyncio.run(fetch_training_data())
    print(f"[INFO] 학습 데이터 로드: {len(df)}건 (최근 7일)")
    print(df['cloud'].value_counts())
    train_all(df)
