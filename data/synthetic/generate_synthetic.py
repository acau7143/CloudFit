"""
합성 데이터 생성기 (v2)
- [8주차] 패턴을 절대값이 아니라 "클라우드별 real 데이터 평균 대비 배율"로 생성
  -> v1에서는 모든 클라우드에 동일한 절대값(예: 정상=CPU 20~50%)을 적용해서
     실제로는 클라우드마다 평소 CPU 수준이 다른데(AWS 2.9%, Azure 0.8%, GCP 21.8%)
     synthetic "정상"조차 real 기준으로는 전부 이상치처럼 보이는 문제가 있었음
     (ml/validate_with_synthetic.py 검증 결과 모든 패턴이 99~100%로 나와서 발견)
- ML 학습에 필요한 다양한 패턴 데이터를 생성해서 DB에 적재
- source='synthetic' 으로 실제 데이터와 구분
"""

import asyncpg
import asyncio
import random
import os
from datetime import datetime, timedelta

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://finops:finops123@localhost:5432/finops_db")

# 생성할 클라우드 / 인스턴스 목록 (5개 패턴을 6개 인스턴스에 하나씩 배정)
INSTANCES = [
    {"cloud": "AWS",   "instance_id": "i-synth-001",  "instance_type": "t3.micro",  "vcpu": 2, "ram_gb": 1.0},
    {"cloud": "AWS",   "instance_id": "i-synth-002",  "instance_type": "t3.small",  "vcpu": 2, "ram_gb": 2.0},
    {"cloud": "Azure", "instance_id": "vm-synth-001", "instance_type": "B1s",       "vcpu": 1, "ram_gb": 1.0},
    {"cloud": "Azure", "instance_id": "vm-synth-002", "instance_type": "B2s",       "vcpu": 2, "ram_gb": 4.0},
    {"cloud": "GCP",   "instance_id": "gce-synth-001","instance_type": "e2-micro",  "vcpu": 2, "ram_gb": 1.0},
    {"cloud": "GCP",   "instance_id": "gce-synth-002","instance_type": "e2-small",  "vcpu": 2, "ram_gb": 2.0},
]

# [8주차] 패턴 = "그 클라우드 real 평균의 몇 배인가"로 정의 (절대값 아님)
PATTERN_MULTIPLIERS = {
    "정상":        {"cpu": (0.7, 1.3),  "mem": (0.95, 1.05), "disk": (0.95, 1.05), "weight": 50},
    "저활용":      {"cpu": (0.1, 0.4),  "mem": (0.7, 0.9),   "disk": (0.9, 1.0),   "weight": 20},
    "과부하":      {"cpu": (3.0, 8.0),  "mem": (1.3, 1.6),   "disk": (1.1, 1.3),   "weight": 15},
    "스파이크":    {"cpu": (6.0, 15.0), "mem": (1.1, 1.3),   "disk": (1.0, 1.1),   "weight": 8},
    "점진적증가":  {"cpu": (1.0, 5.0),  "mem": (1.0, 1.4),   "disk": (1.0, 1.2),   "weight": 7},
}


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


async def fetch_real_baseline(conn) -> dict:
    """클라우드별 real 데이터 평균(cpu/mem/disk)을 조회 - 합성 데이터 생성 기준선으로 사용"""
    rows = await conn.fetch("""
        SELECT cloud,
               AVG(cpu_avg) AS avg_cpu,
               AVG(COALESCE(memory_avg, 0)) AS avg_mem,
               AVG(COALESCE(disk_avg, 0)) AS avg_disk
        FROM resource_metrics
        WHERE source = 'real'
        GROUP BY cloud
    """)
    return {r["cloud"]: {"cpu": r["avg_cpu"], "mem": r["avg_mem"], "disk": r["avg_disk"]} for r in rows}


def generate_metrics(pattern_name: str, baseline: dict, step: int = 0, total_steps: int = 1):
    p = PATTERN_MULTIPLIERS[pattern_name]
    cpu_low, cpu_high = p["cpu"]
    mem_low, mem_high = p["mem"]
    disk_low, disk_high = p["disk"]

    if pattern_name == "점진적증가":
        # step에 따라 배율이 low배 -> high배로 서서히 증가
        progress = step / max(total_steps - 1, 1)
        mult = cpu_low + (cpu_high - cpu_low) * progress
        cpu = baseline["cpu"] * mult
    elif pattern_name == "스파이크":
        # 12포인트(1시간) 중 2포인트만 스파이크, 나머지는 평소 수준
        if step % 12 < 2:
            cpu = baseline["cpu"] * random.uniform(cpu_low, cpu_high)
        else:
            cpu = baseline["cpu"] * random.uniform(0.8, 1.2)
    else:
        cpu = baseline["cpu"] * random.uniform(cpu_low, cpu_high)

    mem = baseline["mem"] * random.uniform(mem_low, mem_high)
    disk = baseline["disk"] * random.uniform(disk_low, disk_high)

    return round(clamp(cpu), 2), round(clamp(mem), 2), round(clamp(disk), 2)


def pick_pattern() -> str:
    patterns = list(PATTERN_MULTIPLIERS.keys())
    weights = [PATTERN_MULTIPLIERS[p]["weight"] for p in patterns]
    return random.choices(patterns, weights=weights, k=1)[0]


async def generate_and_insert(conn, days: int = 30, interval_minutes: int = 5):
    """
    days 일치 데이터를 interval_minutes 간격으로 생성해서 DB에 적재
    기본: 30일 x 5분 간격 = 8,640 포인트 per 인스턴스
    """
    baseline_by_cloud = await fetch_real_baseline(conn)
    print(f"[INFO] real 데이터 기준선: {baseline_by_cloud}")

    now = datetime.utcnow().replace(second=0, microsecond=0)
    start = now - timedelta(days=days)

    total_inserted = 0
    GUARANTEED_PATTERNS = list(PATTERN_MULTIPLIERS.keys())  # 5개 패턴을 순서대로 확보

    for idx, inst in enumerate(INSTANCES):
        cloud = inst["cloud"]
        if cloud not in baseline_by_cloud:
            print(f"[경고] {cloud}에 real 데이터가 아직 없어서 건너뜀 - 기준선을 만들 수 없음")
            continue
        baseline = baseline_by_cloud[cloud]

        # 처음 5개 인스턴스는 5개 패턴에 하나씩 고정 배정, 6번째만 랜덤
        # (가중치 랜덤만 쓰면 낮은 가중치 패턴이 우연히 하나도 안 뽑힐 수 있어서)
        if idx < len(GUARANTEED_PATTERNS):
            pattern_name = GUARANTEED_PATTERNS[idx]
        else:
            pattern_name = pick_pattern()

        timestamps = []
        ts = start
        while ts <= now:
            timestamps.append(ts)
            ts += timedelta(minutes=interval_minutes)

        total_steps = len(timestamps)
        rows = []

        for step, ts in enumerate(timestamps):
            cpu, mem, disk = generate_metrics(pattern_name, baseline, step, total_steps)
            rows.append((
                inst["cloud"],
                inst["instance_id"],
                ts,
                cpu,
                mem,
                disk,
                inst["instance_type"],
                inst["vcpu"],
                inst["ram_gb"],
                "synthetic",
                pattern_name,
            ))

        await conn.executemany("""
            INSERT INTO resource_metrics
                (cloud, instance_id, timestamp, cpu_avg, memory_avg, disk_avg,
                 instance_type, vcpu, ram_gb, source, pattern)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
            ON CONFLICT (cloud, instance_id, timestamp) DO NOTHING
        """, rows)

        print(f"[OK] {inst['cloud']} / {inst['instance_id']} / 패턴={pattern_name} "
              f"(기준 CPU {baseline['cpu']:.2f}%) / {len(rows)}건 삽입")
        total_inserted += len(rows)

    print(f"\n[완료] 총 {total_inserted}건 생성")


async def main():
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await generate_and_insert(conn, days=30, interval_minutes=5)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
