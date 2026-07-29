-- resource_metrics: 5분 간격 자원 사용률 (CPU/메모리/디스크)
CREATE TABLE IF NOT EXISTS resource_metrics (
    id SERIAL PRIMARY KEY,
    cloud VARCHAR(10) NOT NULL,          -- 'AWS' / 'Azure' / 'GCP'
    instance_id VARCHAR(100) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    cpu_avg FLOAT,
    memory_avg FLOAT,
    disk_avg FLOAT,
    instance_type VARCHAR(50),
    vcpu INT,
    ram_gb FLOAT,
    created_at TIMESTAMPTZ DEFAULT now(),
    -- [5주차] 같은 (클라우드, 인스턴스, 시각) 재전송 시 중복 방지
    CONSTRAINT uq_resource_cloud_instance_ts UNIQUE (cloud, instance_id, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_resource_metrics_cloud_time
    ON resource_metrics (cloud, timestamp);
CREATE INDEX IF NOT EXISTS idx_resource_metrics_instance
    ON resource_metrics (instance_id, timestamp);

-- cost_records: 하루 1회, 서비스별로 여러 행 (decisions/0002 참고)
CREATE TABLE IF NOT EXISTS cost_records (
    id SERIAL PRIMARY KEY,
    cloud VARCHAR(10) NOT NULL,          -- 'AWS' / 'Azure' / 'GCP'
    date DATE NOT NULL,
    cost_usd FLOAT NOT NULL,
    currency VARCHAR(10) DEFAULT 'USD',
    service VARCHAR(100),                -- 'Compute Engine', 'Cloud Storage', 'Networking' 등
    granularity VARCHAR(10) DEFAULT 'DAILY',
    created_at TIMESTAMPTZ DEFAULT now(),
    -- [5주차] 같은 (클라우드, 날짜, 서비스) 재전송 시 중복 방지 → 수집기 여러 번 돌려도 안전
    --  주의: service가 NULL이면 Postgres는 NULL을 서로 다른 값으로 취급해 dedup이 안 됨.
    --        수집기는 항상 service 문자열을 채워 보내므로 실데이터에선 문제 없음.
    CONSTRAINT uq_cost_cloud_date_service UNIQUE (cloud, date, service)
);
CREATE INDEX IF NOT EXISTS idx_cost_records_cloud_date
    ON cost_records (cloud, date);
CREATE INDEX IF NOT EXISTS idx_cost_records_cloud_date_service
    ON cost_records (cloud, date, service);
