-- Marker table for geographic locations
CREATE TABLE marker(
    id INTEGER PRIMARY KEY ASC,
    label VARCHAR(16) UNIQUE,
    latitude REAL,
    longitude REAL,
    description TEXT
);

-- Sitemap table for uploaded map files
CREATE TABLE sitemap(
    id INTEGER PRIMARY KEY ASC,
    file_name VARCHAR(64) UNIQUE
);

-- Junction table linking markers to sitemaps with pixel coordinates
CREATE TABLE sitemap_marker (
    id INTEGER PRIMARY KEY ASC,
    marker_id INTEGER NOT NULL,
    sitemap_id INTEGER NOT NULL,
    x_coord INTEGER,
    y_coord INTEGER,
    UNIQUE (marker_id, sitemap_id),
    FOREIGN KEY (marker_id) REFERENCES marker (id) ON DELETE CASCADE,
    FOREIGN KEY (sitemap_id) REFERENCES sitemap (id) ON DELETE CASCADE
);

-- Device table for monitoring equipment
CREATE TABLE device (
    id INTEGER PRIMARY KEY ASC,
    label VARCHAR(16) UNIQUE,
    serial VARCHAR(32),
    device_type VARCHAR(16) NOT NULL
);

-- Analyte table for chemical substances being measured
CREATE TABLE analyte (
    id INTEGER PRIMARY KEY ASC,
    label VARCHAR(16) UNIQUE,
    responder_name VARCHAR(16) UNIQUE,
    dec_pls INTEGER DEFAULT 2,
    hotzone_threshold REAL NOT NULL DEFAULT 0.0,
    warmzone_threshold REAL NOT NULL DEFAULT 0.0,
    fireground_threshold REAL NOT NULL DEFAULT 0.0,
    community_threshold REAL NOT NULL DEFAULT 0.0
);

-- Spot readings from single measurements at a location
CREATE TABLE spot_reading (
    id INTEGER PRIMARY KEY ASC,
    value REAL NOT NULL,
    timestamp TEXT NOT NULL,
    comment TEXT,
    device_id INTEGER,
    analyte_id INTEGER NOT NULL,
    marker_id INTEGER NOT NULL,
    UNIQUE(marker_id, timestamp, analyte_id),
    FOREIGN KEY (device_id) REFERENCES device (id) ON DELETE CASCADE,
    FOREIGN KEY (analyte_id) REFERENCES analyte (id) ON DELETE CASCADE,
    FOREIGN KEY (marker_id) REFERENCES marker (id) ON DELETE CASCADE
);

-- Area locations for continuous monitoring periods
CREATE TABLE area_location (
    id INTEGER PRIMARY KEY ASC,
    start_dt TEXT NOT NULL,
    stop_dt TEXT,
    comment TEXT,
    device_id INTEGER,
    marker_id INTEGER NOT NULL,
    FOREIGN KEY (device_id) REFERENCES device (id) ON DELETE CASCADE,
    FOREIGN KEY (marker_id) REFERENCES marker (id) ON DELETE CASCADE
);

-- Area validations for continuous monitoring periods
CREATE TABLE area_invalidations (
    id INTEGER PRIMARY KEY ASC,
    start_dt TEXT NOT NULL,
    stop_dt TEXT,
    comment TEXT,
    device_id INTEGER,
    analyte_id INTEGER NOT NULL,
    invalid_flag INTEGER DEFAULT 0,
    FOREIGN KEY (device_id) REFERENCES device (id) ON DELETE CASCADE,
    FOREIGN KEY (analyte_id) REFERENCES analyte (id) ON DELETE CASCADE
);

-- Spectral analysis results
CREATE TABLE spectral_result (
    id INTEGER PRIMARY KEY ASC,
    chemicals TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    comment TEXT,
    file_ref VARCHAR(64),
    device_id INTEGER NOT NULL,
    marker_id INTEGER NOT NULL,
    FOREIGN KEY (device_id) REFERENCES device (id) ON DELETE CASCADE,
    FOREIGN KEY (marker_id) REFERENCES marker (id) ON DELETE CASCADE
);

-- Exposure monitoring sessions
CREATE TABLE exposure (
    id INTEGER PRIMARY KEY ASC,
    identifier VARCHAR(64),
    start_dt TEXT NOT NULL,
    stop_dt TEXT,
    area TEXT,
    activities TEXT,
    respiratory VARCHAR(16),
    clothing VARCHAR(16),
    footwear VARCHAR(16),
    device_id INTEGER NOT NULL,
    FOREIGN KEY (device_id) REFERENCES device (id) ON DELETE CASCADE
);

-- Summary readings for exposure sessions
CREATE TABLE exposure_reading(
    id INTEGER PRIMARY KEY ASC,
    mean_value REAL,
    min_value REAL,
    max_value REAL,
    exposure_id INTEGER NOT NULL,
    analyte_id INTEGER NOT NULL,
    device_id INTEGER NOT NULL,
    FOREIGN KEY (exposure_id) REFERENCES exposure (id) ON DELETE CASCADE,
    FOREIGN KEY (analyte_id) REFERENCES analyte (id) ON DELETE CASCADE,
    FOREIGN KEY (device_id) REFERENCES device (id) ON DELETE CASCADE
);

-- Plume modeling results
CREATE TABLE plume(
    id INTEGER PRIMARY KEY ASC,
    model_dt TEXT,
    file_name VARCHAR(64)
);

-- Objectives and planning data
CREATE TABLE objective(
    id INTEGER PRIMARY KEY ASC,
    zone VARCHAR(16),
    objective TEXT,
    strategy TEXT,
    conclusion TEXT,
    data_type VARCHAR(16),
    form VARCHAR(32),
    filter_file_name VARCHAR(64),
    created_at TEXT,
    updated_at TEXT
);

-- Area readings for continuous monitoring periods
CREATE TABLE area_reading (
    id INTEGER PRIMARY KEY ASC,
    timestamp TEXT NOT NULL,
    serial_number VARCHAR(32),
    marker_id INTEGER,
    status VARCHAR(16),
    battery REAL,
    latitude REAL,
    longitude REAL,
    device_id INTEGER,
    FOREIGN KEY (marker_id) REFERENCES marker (id) ON DELETE SET NULL,
    FOREIGN KEY (device_id) REFERENCES device (id) ON DELETE SET NULL
);

-- Junction table for area reading analyte values
CREATE TABLE area_reading_analyte (
    id INTEGER PRIMARY KEY ASC,
    area_reading_id INTEGER NOT NULL,
    analyte_id INTEGER NOT NULL,
    value REAL,
    invalidation_id INTEGER,
    FOREIGN KEY (area_reading_id) REFERENCES area_reading (id) ON DELETE CASCADE,
    FOREIGN KEY (analyte_id) REFERENCES analyte (id) ON DELETE CASCADE,
    FOREIGN KEY (invalidation_id) REFERENCES area_invalidations (id) ON DELETE SET NULL,
    UNIQUE(area_reading_id, analyte_id)
);

-- Auto-populate created_at on insert
CREATE TRIGGER objective_created
AFTER INSERT ON objective
BEGIN
    UPDATE objective
    SET created_at = datetime('now')
    WHERE id = NEW.id;
END;

-- Auto-update updated_at on update
CREATE TRIGGER objective_updated
AFTER UPDATE ON objective
BEGIN
    UPDATE objective
    SET updated_at = datetime('now')
    WHERE id = NEW.id;
END;

-- Performance indexes
CREATE INDEX idx_area_reading_timestamp ON area_reading(timestamp);
CREATE INDEX idx_area_reading_device ON area_reading(device_id);
CREATE INDEX idx_area_reading_marker ON area_reading(marker_id);
CREATE INDEX idx_area_reading_analyte_reading ON area_reading_analyte(area_reading_id);
CREATE INDEX idx_area_reading_analyte_analyte ON area_reading_analyte(analyte_id);
CREATE INDEX idx_area_reading_analyte_invalidation ON area_reading_analyte(invalidation_id);
CREATE INDEX idx_spot_reading_timestamp ON spot_reading(timestamp);
CREATE INDEX idx_spot_reading_marker ON spot_reading(marker_id);
CREATE INDEX idx_spot_reading_device ON spot_reading(device_id);
CREATE INDEX idx_spot_reading_analyte ON spot_reading(analyte_id);
CREATE INDEX idx_area_location_start_dt ON area_location(start_dt);
CREATE INDEX idx_area_location_stop_dt ON area_location(stop_dt);
CREATE INDEX idx_area_location_marker ON area_location(marker_id);
CREATE INDEX idx_exposure_start_dt ON exposure(start_dt);
CREATE INDEX idx_exposure_device ON exposure(device_id);
CREATE INDEX idx_exposure_reading_exposure ON exposure_reading(exposure_id);
CREATE INDEX idx_exposure_reading_analyte ON exposure_reading(analyte_id);
CREATE INDEX idx_spectral_result_timestamp ON spectral_result(timestamp);
CREATE INDEX idx_spectral_result_marker ON spectral_result(marker_id);
CREATE INDEX idx_sitemap_marker_sitemap ON sitemap_marker(sitemap_id);
CREATE INDEX idx_sitemap_marker_marker ON sitemap_marker(marker_id);
