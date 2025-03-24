package sync

import (
	"context"
	"fmt"
	"log"
	"strings"
	"time"

	"github.com/google/go-github/v57/github"
	"github.com/wesm/github-issue-digest/internal/api"
	"github.com/wesm/github-issue-digest/internal/db"
)

// Syncer handles syncing GitHub issues to the local database
type Syncer struct {
	db     *db.DB
	client *api.GitHubClient
}

// New creates a new syncer
func New(db *db.DB, client *api.GitHubClient) *Syncer {
	return &Syncer{
		db:     db,
		client: client,
	}
}

// SyncRepository syncs a repository's issues to the local database
func (s *Syncer) SyncRepository(ctx context.Context, owner, name string) error {
	fullName := fmt.Sprintf("%s/%s", owner, name)
	
	// Get the repository from GitHub
	repo, err := s.client.GetRepository(ctx, owner, name)
	if err != nil {
		return fmt.Errorf("failed to get repository %s: %w", fullName, err)
	}

	// Save the repository to the database
	if err := s.db.SaveRepository(repo); err != nil {
		return fmt.Errorf("failed to save repository %s: %w", fullName, err)
	}

	// Get the last sync time for this repository
	lastSyncTime, err := s.db.GetLastSyncTime(fullName)
	if err != nil {
		return fmt.Errorf("failed to get last sync time for %s: %w", fullName, err)
	}

	log.Printf("Syncing repository %s (last sync: %v)", fullName, lastSyncTime)

	// Get issues updated since the last sync
	issues, err := s.client.GetIssues(ctx, owner, name, lastSyncTime)
	if err != nil {
		return fmt.Errorf("failed to get issues for %s: %w", fullName, err)
	}

	log.Printf("Found %d issues updated since last sync", len(issues))

	// Process each issue
	for _, issue := range issues {
		if err := s.processIssue(ctx, repo.ID, owner, name, issue); err != nil {
			log.Printf("Error processing issue #%d: %v", issue.GetNumber(), err)
			// Continue with other issues even if one fails
			continue
		}
	}

	// Update the last sync time
	if err := s.db.UpdateLastSyncTime(fullName, time.Now()); err != nil {
		return fmt.Errorf("failed to update last sync time for %s: %w", fullName, err)
	}

	log.Printf("Successfully synced repository %s", fullName)
	return nil
}

// processIssue processes a single issue and its related data
func (s *Syncer) processIssue(ctx context.Context, repoID int64, owner, name string, ghIssue *github.Issue) error {
	// Skip pull requests if the issue object represents a pull request
	if ghIssue.IsPullRequest() {
		return nil
	}

	// Save the issue creator
	if ghIssue.User != nil {
		user := api.ConvertGitHubUser(ghIssue.User)
		if err := s.db.SaveUser(user); err != nil {
			return fmt.Errorf("failed to save user %s: %w", user.Login, err)
		}
	}

	// Save the issue
	issue := api.ConvertGitHubIssue(ghIssue)
	if err := s.db.SaveIssue(issue, repoID); err != nil {
		return fmt.Errorf("failed to save issue #%d: %w", issue.Number, err)
	}

	// Process labels
	for _, label := range ghIssue.Labels {
		modelLabel := api.ConvertGitHubLabel(label)
		labelID, err := s.db.SaveLabel(modelLabel)
		if err != nil {
			return fmt.Errorf("failed to save label %s: %w", *label.Name, err)
		}

		if err := s.db.SaveIssueLabel(issue.ID, labelID); err != nil {
			return fmt.Errorf("failed to save issue-label relationship: %w", err)
		}
	}

	// Get and process comments
	comments, err := s.client.GetIssueComments(ctx, owner, name, issue.Number)
	if err != nil {
		return fmt.Errorf("failed to get comments for issue #%d: %w", issue.Number, err)
	}

	for _, comment := range comments {
		// Save the comment author
		if comment.User != nil {
			user := api.ConvertGitHubUser(comment.User)
			if err := s.db.SaveUser(user); err != nil {
				return fmt.Errorf("failed to save user %s: %w", user.Login, err)
			}
		}

		// Save the comment
		modelComment := api.ConvertGitHubComment(comment, issue.ID)
		if err := s.db.SaveComment(modelComment); err != nil {
			return fmt.Errorf("failed to save comment: %w", err)
		}
	}

	return nil
}

// ParseRepositoryString parses a repository string in the format "owner/name"
func ParseRepositoryString(repoStr string) (string, string, error) {
	parts := strings.Split(repoStr, "/")
	if len(parts) != 2 {
		return "", "", fmt.Errorf("invalid repository format, expected 'owner/name', got '%s'", repoStr)
	}
	return parts[0], parts[1], nil
}
