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
    source VARCHAR(20) DEFAULT 'real',   -- [8주차] 'real'(실데이터) / 'synthetic'(stress-ng 생성)
    pattern VARCHAR(20),                 -- [8주차] synthetic 데이터의 부하 패턴 종류 (예: cpu_spike, idle 등) - real이면 NULL
    -- [5주차] 같은 (클라우드, 인스턴스, 시각) 재전송 시 중복 방지
    CONSTRAINT uq_resource_cloud_instance_ts UNIQUE (cloud, instance_id, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_resource_metrics_cloud_time
    ON resource_metrics (cloud, timestamp);
CREATE INDEX IF NOT EXISTS idx_resource_metrics_instance
    ON resource_metrics (instance_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_resource_metrics_source
    ON resource_metrics (source);
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
-- anomaly_results: ML(Isolation Forest) 이상탐지 결과 저장
CREATE TABLE IF NOT EXISTS anomaly_results (
    id           SERIAL PRIMARY KEY,
    cloud        VARCHAR(10)  NOT NULL,          -- 'AWS' / 'Azure' / 'GCP'
    instance_id  VARCHAR(100),
    timestamp    TIMESTAMPTZ  NOT NULL,
    cpu_avg      FLOAT,
    memory_avg   FLOAT,                           -- [8주차] 어떤 지표 때문에 이상 판정됐는지 확인용
    disk_avg     FLOAT,                            -- [8주차] 어떤 지표 때문에 이상 판정됐는지 확인용
    anomaly      BOOLEAN      NOT NULL,           -- TRUE: 이상, FALSE: 정상
    score        FLOAT,                           -- 낮을수록 이상 (Isolation Forest score)
    detected_at  TIMESTAMPTZ  DEFAULT now(),
    -- [7주차] 같은 (클라우드, 인스턴스, 시각) 중복 탐지 방지 → 10분 크론 겹침 구간 대비
    CONSTRAINT uq_anomaly_cloud_instance_ts UNIQUE (cloud, instance_id, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_anomaly_results_cloud_time
    ON anomaly_results (cloud, timestamp);
CREATE INDEX IF NOT EXISTS idx_anomaly_results_anomaly
    ON anomaly_results (anomaly, timestamp);

-- recommendations: 비용 최적화 추천 (저활용 인스턴스 다운사이징 등)
CREATE TABLE IF NOT EXISTS recommendations (
    id             SERIAL PRIMARY KEY,
    cloud          VARCHAR(10)  NOT NULL,          -- 'AWS' / 'Azure' / 'GCP'
    instance_id    VARCHAR(100) NOT NULL,
    avg_cpu_7d     FLOAT,
    total_cost_7d  FLOAT,
    recommendation VARCHAR(50),                    -- 'downsize' / 'terminate' / 'keep'
    reason         TEXT,
    generated_at   TIMESTAMPTZ DEFAULT now(),
    -- [8주차] 실행할 때마다 새 행으로 쌓임 (이력 보존) - 같은 시각 재실행 시 중복만 방지
    CONSTRAINT uq_reco_cloud_instance UNIQUE (cloud, instance_id, generated_at)
);
CREATE INDEX IF NOT EXISTS idx_recommendations_cloud_time
    ON recommendations (cloud, generated_at);

-- [9주차] 미사용 리소스 탐지
CREATE TABLE IF NOT EXISTS unused_resources (
    id            SERIAL PRIMARY KEY,
    cloud         VARCHAR(10)  NOT NULL,          -- 'AWS' / 'Azure' / 'GCP'
    resource_type VARCHAR(30)  NOT NULL,           -- 'volume' / 'disk' / 'ip'
    resource_id   VARCHAR(200) NOT NULL,
    reason        TEXT,
    detected_at   TIMESTAMPTZ  DEFAULT now(),
    resolved_at   TIMESTAMPTZ,
    CONSTRAINT uq_unused_cloud_resource UNIQUE (cloud, resource_id, detected_at)
);
CREATE INDEX IF NOT EXISTS idx_unused_resources_cloud ON unused_resources (cloud, detected_at);

-- [10주차] 예약 인스턴스 추천 컬럼 추가
ALTER TABLE recommendations ADD COLUMN IF NOT EXISTS commitment_recommendation VARCHAR(50);
ALTER TABLE recommendations ADD COLUMN IF NOT EXISTS estimated_discount_pct FLOAT;

-- [10주차] 비용 예측
CREATE TABLE IF NOT EXISTS cost_forecast (
    id             SERIAL PRIMARY KEY,
    cloud          VARCHAR(10)  NOT NULL,
    forecast_date  DATE         NOT NULL,
    predicted_cost FLOAT,
    lower_bound    FLOAT,
    upper_bound    FLOAT,
    generated_at   TIMESTAMPTZ  DEFAULT now(),
    CONSTRAINT uq_forecast_cloud_date UNIQUE (cloud, forecast_date, generated_at)
);
