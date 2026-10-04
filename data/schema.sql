CREATE TABLE IF NOT EXISTS locations (
    id INTEGER PRIMARY KEY,
    canonical_name TEXT NOT NULL UNIQUE,
    aliases TEXT NOT NULL DEFAULT '',
    building TEXT NOT NULL,
    floor TEXT NOT NULL,
    room TEXT NOT NULL DEFAULT '',
    directions TEXT NOT NULL,
    accessible_directions TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    services TEXT NOT NULL DEFAULT '',
    keywords TEXT NOT NULL DEFAULT '',
    example_questions TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_locations_active_name
ON locations(active, canonical_name);

CREATE TABLE IF NOT EXISTS location_embeddings (
    location_id INTEGER PRIMARY KEY,
    model_name TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    embedding TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (location_id) REFERENCES locations(id) ON DELETE CASCADE
);
