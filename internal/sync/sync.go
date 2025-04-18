package sync

import (
	"context"
	"errors"
	"fmt"
	"log"
	"strings"
	"sync"
	"time"

	"github.com/google/go-github/v57/github"
	"github.com/wesm/argh/internal/api"
	"github.com/wesm/argh/internal/db"
)

// Syncer represents a syncer for syncing GitHub issues to a local database
type Syncer struct {
	db         *db.DB
	restClient *api.GitHubClient
	workers    int
}

// NewSyncer creates a new syncer
func NewSyncer(db *db.DB, token string, workers int, _ bool) *Syncer {
	// We're ignoring the GraphQL flag parameter (kept for backward compatibility)
	restClient := api.NewGitHubClient(token)
	return &Syncer{
		db:         db,
		restClient: restClient,
		workers:    workers,
	}
}

// SetWorkers sets the number of parallel workers
func (s *Syncer) SetWorkers(workers int) {
	if workers < 1 {
		workers = 1
	}
	if workers > 10 {
		workers = 10 // Cap at 10 to avoid overwhelming GitHub API
	}
	s.workers = workers
}

// SyncRepository syncs a repository's issues to the local database
func (s *Syncer) SyncRepository(ctx context.Context, owner, name string) error {
	fullName := fmt.Sprintf("%s/%s", owner, name)
	
	// Get the repository information
	repo, ownerUser, err := s.restClient.GetRepository(ctx, owner, name)
	if err != nil {
		return fmt.Errorf("failed to get repository %s: %w", fullName, err)
	}

	// Save the repository owner as a user
	if err := s.db.SaveUser(ownerUser); err != nil {
		return fmt.Errorf("failed to save repository owner %s: %w", ownerUser.Login, err)
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
	log.Printf("Fetching issues from GitHub for %s...", fullName)
	issues, err := s.restClient.GetIssues(ctx, owner, name, lastSyncTime)
	if err != nil {
		return fmt.Errorf("failed to get issues for %s: %w", fullName, err)
	}

	totalIssues := len(issues)
	log.Printf("Found %d issues updated since last sync", totalIssues)

	if totalIssues == 0 {
		log.Printf("No issues to sync for %s", fullName)
		// Update the last sync time even if no issues were found
		if err := s.db.UpdateLastSyncTime(fullName, time.Now()); err != nil {
			return fmt.Errorf("failed to update last sync time for %s: %w", fullName, err)
		}
		return nil
	}

	// Process issues in parallel using a worker pool
	log.Printf("Processing issues with %d parallel workers", s.workers)
	
	// Create a channel to send issues to workers
	issuesChan := make(chan *github.Issue, totalIssues)
	
	// Create a wait group to wait for all workers to finish
	var wg sync.WaitGroup
	
	// Create a mutex for thread-safe progress tracking
	var progressMutex sync.Mutex
	processed := 0
	lastProgressUpdate := time.Now()
	progressInterval := 5 * time.Second // Update progress at most every 5 seconds
	
	// Create a channel to collect errors
	errorsChan := make(chan error, totalIssues)
	
	// Create a context with cancellation for all workers
	workerCtx, cancelWorkers := context.WithCancel(ctx)
	defer cancelWorkers()
	
	// Create a channel to signal rate limit detection
	rateLimitChan := make(chan time.Time, s.workers)
	
	// Start worker goroutines
	for i := 0; i < s.workers; i++ {
		wg.Add(1)
		go func(workerID int) {
			defer wg.Done()
			
			for ghIssue := range issuesChan {
				select {
				case <-ctx.Done():
					return // Context canceled
				default:
					// Continue processing
				}
				
				// Process issue
				err := s.processIssue(workerCtx, repo.ID, owner, name, ghIssue)
				if err != nil {
					// Check if it's a rate limit error
					var rateLimitErr *api.RateLimitError
					if errors.As(err, &rateLimitErr) {
						// Signal rate limit hit to other workers with the reset time
						select {
						case rateLimitChan <- rateLimitErr.ResetTime:
							// Successfully sent rate limit signal
						default:
							// Channel buffer full, another worker already reported
						}
						
						// Log rate limit error immediately
						log.Printf("Error: issue #%d: rate limit error: %v", ghIssue.GetNumber(), err)
					} else {
						// Log other errors immediately
						log.Printf("Error: issue #%d: %v", ghIssue.GetNumber(), err)
					}
					
					// Still record the error for counting purposes
					errorsChan <- err
				}
				
				// Update progress with mutex to avoid race conditions
				progressMutex.Lock()
				processed++
				current := processed // Capture for logging
				
				// Show progress based on time interval or at beginning/end
				shouldLog := current == 1 || current == totalIssues || 
					time.Since(lastProgressUpdate) >= progressInterval
				
				if shouldLog {
					log.Printf("Progress: %d/%d issues (%.1f%%)", 
						current, totalIssues, float64(current)/float64(totalIssues)*100.0)
					lastProgressUpdate = time.Now()
				}
				progressMutex.Unlock()
			}
		}(i)
	}
	
	// Start a goroutine to monitor for rate limit signals
	go func() {
		for resetTime := range rateLimitChan {
			waitTime := time.Until(resetTime)
			if waitTime < 0 {
				waitTime = 30 * time.Second
			}
			
			// Cap wait time to avoid extremely long waits
			if waitTime > 15*time.Minute {
				waitTime = 15 * time.Minute
			}
			
			log.Printf("Rate limit detected! Waiting until %s (%s from now) before continuing...", 
				resetTime.Format(time.RFC3339), waitTime.Round(time.Second))
			
			// The API client will handle individual retries, but we'll pause sending new issues
			time.Sleep(waitTime)
		}
	}()
	
	// Send issues to the channel
	for _, issue := range issues {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case issuesChan <- issue:
			// Successfully sent issue to worker
		}
	}
	close(issuesChan)
	
	// Wait for all workers to finish
	wg.Wait()
	close(errorsChan)
	close(rateLimitChan)
	
	// Count the total errors (already logged during processing)
	errorCount := 0
	for range errorsChan {
		errorCount++
	}
	
	if errorCount > 0 {
		log.Printf("Completed with %d errors", errorCount)
	}
	
	// Update the last sync time
	if err := s.db.UpdateLastSyncTime(fullName, time.Now()); err != nil {
		return fmt.Errorf("failed to update last sync time for %s: %w", fullName, err)
	}

	log.Printf("Successfully synced repository %s (%d issues processed)", fullName, totalIssues)
	return nil
}

// processIssue processes a single issue and its related data
func (s *Syncer) processIssue(ctx context.Context, repoID int64, owner, name string, ghIssue *github.Issue) error {
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
			// Log the error but continue processing other labels
			log.Printf("issue #%d: failed to save label %s: %v", issue.Number, *label.Name, err)
			continue
		}

		if err := s.db.SaveIssueLabel(issue.ID, labelID); err != nil {
			// Log the error but continue processing other labels
			log.Printf("issue #%d: failed to save label %s association: %v", issue.Number, *label.Name, err)
			continue
		}
	}

	// Get and process comments
	comments, err := s.restClient.GetIssueComments(ctx, owner, name, issue.Number)
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
