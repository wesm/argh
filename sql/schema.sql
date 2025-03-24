-- GIRD Database Schema

-- Repository information
CREATE TABLE IF NOT EXISTS repositories (
    id INTEGER PRIMARY KEY,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    full_name TEXT NOT NULL UNIQUE
);

-- GitHub users
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    login TEXT NOT NULL UNIQUE,
    avatar_url TEXT
);

-- Issues and pull requests
CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY,
    number INTEGER NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    state TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    closed_at TIMESTAMP,
    user_id INTEGER,
    repository_id INTEGER NOT NULL,
    is_pull_request BOOLEAN NOT NULL DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (repository_id) REFERENCES repositories(id),
    UNIQUE(repository_id, number)
);

-- Comments on issues and pull requests
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY,
    issue_id INTEGER NOT NULL,
    user_id INTEGER,
    body TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    FOREIGN KEY (issue_id) REFERENCES issues(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Labels for issues and pull requests
CREATE TABLE IF NOT EXISTS labels (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    color TEXT NOT NULL,
    UNIQUE(name, color)
);

-- Many-to-many relationship between issues and labels
CREATE TABLE IF NOT EXISTS issue_labels (
    issue_id INTEGER NOT NULL,
    label_id INTEGER NOT NULL,
    PRIMARY KEY (issue_id, label_id),
    FOREIGN KEY (issue_id) REFERENCES issues(id),
    FOREIGN KEY (label_id) REFERENCES labels(id)
);

-- Tracks the last successful sync for each repository
CREATE TABLE IF NOT EXISTS sync_metadata (
    repository TEXT PRIMARY KEY,
    last_sync_time TIMESTAMP NOT NULL
);
