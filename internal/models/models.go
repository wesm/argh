package models

import (
	"time"
)

// Repository represents a GitHub repository
type Repository struct {
	ID       int64
	Owner    string
	Name     string
	FullName string
}

// User represents a GitHub user
type User struct {
	ID        int64
	Login     string
	AvatarURL string
}

// Issue represents a GitHub issue
type Issue struct {
	ID        int64
	Number    int
	Title     string
	Body      string
	State     string
	CreatedAt time.Time
	UpdatedAt time.Time
	ClosedAt  *time.Time
	UserID    int64
}

// Comment represents a GitHub issue comment
type Comment struct {
	ID        int64
	IssueID   int64
	UserID    int64
	Body      string
	CreatedAt time.Time
	UpdatedAt time.Time
}

// Label represents a GitHub label
type Label struct {
	ID    int64
	Name  string
	Color string
}

// IssueLabel represents a many-to-many relationship between issues and labels
type IssueLabel struct {
	IssueID int64
	LabelID int64
}

// SyncMetadata tracks the last successful sync for a repository
type SyncMetadata struct {
	Repository   string
	LastSyncTime time.Time
}
