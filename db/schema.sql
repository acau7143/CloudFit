-- resource_metrics: 5분 간격 자원 사용률 (CPU/메모리/디스크)
CREATE TABLE IF NOT EXISTS resource_metrics (
    id SERIAL PRIMARY KEY,
    cloud VARCHAR(10) NOT NULL,          -- 'AWS' / 'Azure' / 'GCP'
    instance_id VARCHAR(100),
    timestamp TIMESTAMPTZ NOT NULL,
    cpu_avg FLOAT,
    memory_avg FLOAT,
    disk_avg FLOAT,
    instance_type VARCHAR(50),
    vcpu INT,
    ram_gb FLOAT,
    created_at TIMESTAMPTZ DEFAULT now()
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
    service VARCHAR(100),                -- 'Compute Engine', 'Cloud Storage', 'EC2' 등
    granularity VARCHAR(10) DEFAULT 'DAILY',
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_cost_records_cloud_date
    ON cost_records (cloud, date);
CREATE INDEX IF NOT EXISTS idx_cost_records_cloud_date_service
    ON cost_records (cloud, date, service);
