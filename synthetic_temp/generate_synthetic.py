import asyncpg
import asyncio
import random
import os
from datetime import datetime, timedelta

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://finops:finops123@localhost:5432/finops_db")

# 생성할 클라우드 / 인스턴스 목록
INSTANCES = [
    {"cloud": "AWS",   "instance_id": "i-synth-001", "instance_type": "t3.micro",  "vcpu": 2,  "ram_gb": 1.0},
    {"cloud": "AWS",   "instance_id": "i-synth-002", "instance_type": "t3.small",  "vcpu": 2,  "ram_gb": 2.0},
    {"cloud": "Azure", "instance_id": "vm-synth-001","instance_type": "B1s",        "vcpu": 1,  "ram_gb": 1.0},
    {"cloud": "Azure", "instance_id": "vm-synth-002","instance_type": "B2s",        "vcpu": 2,  "ram_gb": 4.0},
    {"cloud": "GCP",   "instance_id": "gce-synth-001","instance_type":"e2-micro",   "vcpu": 2,  "ram_gb": 1.0},
    {"cloud": "GCP",   "instance_id": "gce-synth-002","instance_type":"e2-small",   "vcpu": 2,  "ram_gb": 2.0},
]

# 패턴 정의
PATTERNS = {
    "정상":        {"cpu": (20, 50),  "mem": (30, 60),  "disk": (30, 60),  "weight": 50},
    "저활용":      {"cpu": (3,  15),  "mem": (5,  20),  "disk": (10, 30),  "weight": 20},
    "과부하":      {"cpu": (85, 100), "mem": (80, 95),  "disk": (70, 90),  "weight": 15},
    "스파이크":    {"cpu": (90, 100), "mem": (50, 70),  "disk": (30, 50),  "weight": 8},
    "점진적증가":  {"cpu": (10, 95),  "mem": (20, 80),  "disk": (20, 70),  "weight": 7},
}


def generate_cpu(pattern_name: str, step: int = 0, total_steps: int = 1) -> float:
    p = PATTERNS[pattern_name]
    low, high = p["cpu"]

    if pattern_name == "점진적증가":
        # step에 따라 CPU가 low → high로 서서히 증가
        progress = step / max(total_steps - 1, 1)
        base = low + (high - low) * progress
        return round(min(base + random.uniform(-5, 5), 100), 2)

    if pattern_name == "스파이크":
        # 스파이크 패턴: 짧은 구간에만 높고 나머지는 낮음
        if step % 12 < 2:   # 12포인트(1시간) 중 2포인트만 스파이크
            return round(random.uniform(low, high), 2)
        else:
            return round(random.uniform(5, 20), 2)

    return round(random.uniform(low, high), 2)


def pick_pattern() -> str:
    patterns = list(PATTERNS.keys())
    weights  = [PATTERNS[p]["weight"] for p in patterns]
    return random.choices(patterns, weights=weights, k=1)[0]


async def generate_and_insert(conn, days: int = 30, interval_minutes: int = 5):
    """
    days 일치 데이터를 interval_minutes 간격으로 생성해서 DB에 적재
    기본: 30일 × 5분 간격 = 8,640 포인트 per 인스턴스
    """
    now   = datetime.utcnow().replace(second=0, microsecond=0)
    start = now - timedelta(days=days)

    total_inserted = 0
    GUARANTEED_PATTERNS = list(PATTERNS.keys())  # 5개 패턴 이름을 순서대로 확보

    for idx, inst in enumerate(INSTANCES):
        # 처음 5개 인스턴스는 패턴을 하나씩 확정 배정, 6번째 인스턴스만 랜덤
        if idx < len(GUARANTEED_PATTERNS):
            pattern_name = GUARANTEED_PATTERNS[idx]
        else:
            pattern_name = pick_pattern()

        timestamps   = []
        ts = start
        while ts <= now:
            timestamps.append(ts)
            ts += timedelta(minutes=interval_minutes)

        total_steps = len(timestamps)
        rows = []

        for step, ts in enumerate(timestamps):
            cpu  = generate_cpu(pattern_name, step, total_steps)
            p    = PATTERNS[pattern_name]
            mem  = round(random.uniform(*p["mem"]),  2)
            disk = round(random.uniform(*p["disk"]), 2)

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

        # 배치 INSERT (ON CONFLICT DO NOTHING 으로 중복 방지)
        await conn.executemany("""
            INSERT INTO resource_metrics
                (cloud, instance_id, timestamp, cpu_avg, memory_avg, disk_avg,
                 instance_type, vcpu, ram_gb, source, pattern)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
            ON CONFLICT (cloud, instance_id, timestamp) DO NOTHING
        """, rows)

        print(f"[OK] {inst['cloud']} / {inst['instance_id']} / 패턴={pattern_name} / {len(rows)}건 삽입")
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