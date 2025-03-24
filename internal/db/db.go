package db

import (
	"database/sql"
	"fmt"
	"time"

	"github.com/wesm/github-issue-digest/internal/models"
	_ "github.com/mattn/go-sqlite3"
)

// DB represents the database connection
type DB struct {
	*sql.DB
}

// New creates a new database connection
func New(dbPath string) (*DB, error) {
	db, err := sql.Open("sqlite3", dbPath)
	if err != nil {
		return nil, fmt.Errorf("failed to open database: %w", err)
	}

	if err := db.Ping(); err != nil {
		return nil, fmt.Errorf("failed to ping database: %w", err)
	}

	return &DB{DB: db}, nil
}

// Initialize creates the database schema if it doesn't exist
func (db *DB) Initialize() error {
	schema := `
	CREATE TABLE IF NOT EXISTS repositories (
		id INTEGER PRIMARY KEY,
		owner TEXT NOT NULL,
		name TEXT NOT NULL,
		full_name TEXT NOT NULL UNIQUE
	);

	CREATE TABLE IF NOT EXISTS users (
		id INTEGER PRIMARY KEY,
		login TEXT NOT NULL UNIQUE,
		avatar_url TEXT
	);

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

	CREATE TABLE IF NOT EXISTS labels (
		id INTEGER PRIMARY KEY,
		name TEXT NOT NULL,
		color TEXT NOT NULL,
		UNIQUE(name, color)
	);

	CREATE TABLE IF NOT EXISTS issue_labels (
		issue_id INTEGER NOT NULL,
		label_id INTEGER NOT NULL,
		PRIMARY KEY (issue_id, label_id),
		FOREIGN KEY (issue_id) REFERENCES issues(id),
		FOREIGN KEY (label_id) REFERENCES labels(id)
	);

	CREATE TABLE IF NOT EXISTS sync_metadata (
		repository TEXT PRIMARY KEY,
		last_sync_time TIMESTAMP NOT NULL
	);
	`

	_, err := db.Exec(schema)
	if err != nil {
		return fmt.Errorf("failed to create schema: %w", err)
	}

	return nil
}

// SaveRepository saves a repository to the database
func (db *DB) SaveRepository(repo *models.Repository) error {
	query := `
	INSERT INTO repositories (id, owner, name, full_name)
	VALUES (?, ?, ?, ?)
	ON CONFLICT(full_name) DO UPDATE SET
		owner = excluded.owner,
		name = excluded.name
	`

	_, err := db.Exec(query, repo.ID, repo.Owner, repo.Name, repo.FullName)
	if err != nil {
		return fmt.Errorf("failed to save repository: %w", err)
	}

	return nil
}

// SaveUser saves a user to the database
func (db *DB) SaveUser(user *models.User) error {
	query := `
	INSERT INTO users (id, login, avatar_url)
	VALUES (?, ?, ?)
	ON CONFLICT(id) DO UPDATE SET
		login = excluded.login,
		avatar_url = excluded.avatar_url
	`

	_, err := db.Exec(query, user.ID, user.Login, user.AvatarURL)
	if err != nil {
		return fmt.Errorf("failed to save user: %w", err)
	}

	return nil
}

// SaveIssue saves an issue to the database
func (db *DB) SaveIssue(issue *models.Issue, repoID int64) error {
	query := `
	INSERT INTO issues (id, number, title, body, state, created_at, updated_at, closed_at, user_id, repository_id, is_pull_request)
	VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
	ON CONFLICT(repository_id, number) DO UPDATE SET
		title = excluded.title,
		body = excluded.body,
		state = excluded.state,
		updated_at = excluded.updated_at,
		closed_at = excluded.closed_at,
		user_id = excluded.user_id,
		is_pull_request = excluded.is_pull_request
	`

	_, err := db.Exec(
		query,
		issue.ID,
		issue.Number,
		issue.Title,
		issue.Body,
		issue.State,
		issue.CreatedAt,
		issue.UpdatedAt,
		issue.ClosedAt,
		issue.UserID,
		repoID,
		issue.IsPullRequest,
	)
	if err != nil {
		return fmt.Errorf("failed to save issue: %w", err)
	}

	return nil
}

// SaveComment saves a comment to the database
func (db *DB) SaveComment(comment *models.Comment) error {
	query := `
	INSERT INTO comments (id, issue_id, user_id, body, created_at, updated_at)
	VALUES (?, ?, ?, ?, ?, ?)
	ON CONFLICT(id) DO UPDATE SET
		body = excluded.body,
		updated_at = excluded.updated_at
	`

	_, err := db.Exec(
		query,
		comment.ID,
		comment.IssueID,
		comment.UserID,
		comment.Body,
		comment.CreatedAt,
		comment.UpdatedAt,
	)
	if err != nil {
		return fmt.Errorf("failed to save comment: %w", err)
	}

	return nil
}

// SaveLabel saves a label to the database
func (db *DB) SaveLabel(label *models.Label) (int64, error) {
	query := `
	INSERT INTO labels (id, name, color)
	VALUES (?, ?, ?)
	ON CONFLICT(id) DO UPDATE SET
		name = excluded.name,
		color = excluded.color
	RETURNING id
	`

	var id int64
	err := db.QueryRow(query, label.ID, label.Name, label.Color).Scan(&id)
	if err != nil {
		// If RETURNING is not supported, try a different approach
		_, err = db.Exec(
			`INSERT INTO labels (id, name, color)
			VALUES (?, ?, ?)
			ON CONFLICT(id) DO UPDATE SET
				name = excluded.name,
				color = excluded.color`,
			label.ID, label.Name, label.Color,
		)
		if err != nil {
			return 0, fmt.Errorf("failed to save label: %w", err)
		}
		id = label.ID
	}

	return id, nil
}

// SaveIssueLabel saves an issue-label relationship
func (db *DB) SaveIssueLabel(issueID, labelID int64) error {
	query := `
	INSERT INTO issue_labels (issue_id, label_id)
	VALUES (?, ?)
	ON CONFLICT(issue_id, label_id) DO NOTHING
	`

	_, err := db.Exec(query, issueID, labelID)
	if err != nil {
		return fmt.Errorf("failed to save issue-label relationship: %w", err)
	}

	return nil
}

// GetLastSyncTime gets the last sync time for a repository
func (db *DB) GetLastSyncTime(repoFullName string) (time.Time, error) {
	var lastSyncTime time.Time
	query := `SELECT last_sync_time FROM sync_metadata WHERE repository = ?`
	
	err := db.QueryRow(query, repoFullName).Scan(&lastSyncTime)
	if err != nil {
		if err == sql.ErrNoRows {
			// If no sync metadata exists, return zero time
			return time.Time{}, nil
		}
		return time.Time{}, fmt.Errorf("failed to get last sync time: %w", err)
	}

	return lastSyncTime, nil
}

// UpdateLastSyncTime updates the last sync time for a repository
func (db *DB) UpdateLastSyncTime(repoFullName string, syncTime time.Time) error {
	query := `
	INSERT INTO sync_metadata (repository, last_sync_time)
	VALUES (?, ?)
	ON CONFLICT(repository) DO UPDATE SET
		last_sync_time = excluded.last_sync_time
	`

	_, err := db.Exec(query, repoFullName, syncTime)
	if err != nil {
		return fmt.Errorf("failed to update last sync time: %w", err)
	}

	return nil
}

// GetRepositoryByFullName gets a repository by its full name
func (db *DB) GetRepositoryByFullName(fullName string) (*models.Repository, error) {
	query := `SELECT id, owner, name, full_name FROM repositories WHERE full_name = ?`
	
	var repo models.Repository
	err := db.QueryRow(query, fullName).Scan(&repo.ID, &repo.Owner, &repo.Name, &repo.FullName)
	if err != nil {
		if err == sql.ErrNoRows {
			return nil, nil
		}
		return nil, fmt.Errorf("failed to get repository: %w", err)
	}

	return &repo, nil
}

// Close closes the database connection
func (db *DB) Close() error {
	return db.DB.Close()
}
