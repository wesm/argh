package api

import (
	"context"
	"errors"
	"fmt"
	"log"
	"net/http"
	"strconv"
	"time"

	"github.com/google/go-github/v57/github"
	"github.com/wesm/argh/internal/models"
	"golang.org/x/oauth2"
)

// RateLimitError represents a GitHub API rate limit error
type RateLimitError struct {
	Err       error
	ResetTime time.Time
}

func (e *RateLimitError) Error() string {
	return fmt.Sprintf("API rate limit exceeded, reset at %s: %v",
		e.ResetTime.Format(time.RFC3339), e.Err)
}

func (e *RateLimitError) Unwrap() error {
	return e.Err
}

// GitHubClient represents a client for the GitHub API
type GitHubClient struct {
	client *github.Client
}

// NewGitHubClient creates a new GitHub API client
func NewGitHubClient(token string) *GitHubClient {
	var tc *http.Client

	if token != "" {
		// Create an authenticated client if a token is provided
		ts := oauth2.StaticTokenSource(
			&oauth2.Token{AccessToken: token},
		)
		tc = oauth2.NewClient(context.Background(), ts)
	}

	client := github.NewClient(tc)
	return &GitHubClient{client: client}
}

// handleRateLimit checks if the error is a rate limit error and returns a RateLimitError
func (c *GitHubClient) handleRateLimit(err error, resp *github.Response) error {
	if err == nil {
		return nil
	}

	// Check if this is a rate limit error
	var rateLimitErr *github.RateLimitError
	if errors.As(err, &rateLimitErr) {
		// Get the reset time from the error if available
		resetTime := time.Now().Add(1 * time.Hour) // Default fallback

		if rateLimitErr.Rate.Reset.Time.After(time.Now()) {
			resetTime = rateLimitErr.Rate.Reset.Time
		} else if resp != nil && resp.Response != nil {
			// Try to get the reset time from the response headers
			resetHeader := resp.Response.Header.Get("X-RateLimit-Reset")
			if resetHeader != "" {
				resetUnix, parseErr := strconv.ParseInt(resetHeader, 10, 64)
				if parseErr == nil {
					resetTime = time.Unix(resetUnix, 0)
				}
			}
		}

		return &RateLimitError{
			Err:       err,
			ResetTime: resetTime,
		}
	}

	// Not a rate limit error, return as is
	return err
}

// executeWithRetry executes an operation with retry logic for rate limit errors
func (c *GitHubClient) executeWithRetry(ctx context.Context, operation string, fn func() (*github.Response, error)) error {
	maxRetries := 5
	retryCount := 0

	for {
		// Check if context is cancelled
		if ctx.Err() != nil {
			return ctx.Err()
		}

		// Execute the operation
		_, err := fn()

		// If no error or not a rate limit error, return
		var rateLimitErr *RateLimitError
		if err == nil || !errors.As(err, &rateLimitErr) {
			return err
		}

		// This is a rate limit error, calculate wait time
		waitTime := time.Until(rateLimitErr.ResetTime)

		// Add a small buffer to ensure the rate limit has reset
		waitTime += 5 * time.Second

		// Cap the wait time to avoid excessive waits
		if waitTime > 1*time.Hour {
			waitTime = 1 * time.Hour
		}

		// If wait time is negative or very small, use a default
		if waitTime < 5*time.Second {
			waitTime = 30 * time.Second
		}

		// Log the rate limit and wait
		log.Printf("Rate limit exceeded for %s. Waiting %s until reset at %s",
			operation, waitTime.Round(time.Second), rateLimitErr.ResetTime.Format(time.RFC3339))

		// Wait until the rate limit resets
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(waitTime):
			// Continue with retry
		}

		retryCount++
		if retryCount >= maxRetries {
			return fmt.Errorf("exceeded maximum retries (%d) for %s: %w", maxRetries, operation, err)
		}

		log.Printf("Retrying %s (attempt %d/%d)...", operation, retryCount, maxRetries)
	}
}

// GetRepository gets a repository by owner and name
func (c *GitHubClient) GetRepository(ctx context.Context, owner, name string) (*models.Repository, *models.User, error) {
	var repo *github.Repository
	var err error

	operation := fmt.Sprintf("get repository %s/%s", owner, name)
	retryErr := c.executeWithRetry(ctx, operation, func() (*github.Response, error) {
		var resp *github.Response
		repo, resp, err = c.client.Repositories.Get(ctx, owner, name)
		return resp, c.handleRateLimit(err, resp)
	})

	if retryErr != nil {
		return nil, nil, fmt.Errorf("failed to get repository: %w", retryErr)
	}

	// Create a User object for the repository owner
	ownerUser := &models.User{
		ID:        HandleGitHubID(repo.GetOwner().GetID()),
		Login:     repo.GetOwner().GetLogin(),
		AvatarURL: repo.GetOwner().GetAvatarURL(),
		Type:      repo.GetOwner().GetType(),
	}

	return &models.Repository{
		ID:       HandleGitHubID(repo.GetID()),
		Owner:    repo.GetOwner().GetLogin(),
		Name:     repo.GetName(),
		FullName: repo.GetFullName(),
	}, ownerUser, nil
}

// GetIssues gets issues for a repository, optionally since a specific time
func (c *GitHubClient) GetIssues(ctx context.Context, owner, name string, since time.Time) ([]*github.Issue, error) {
	var allIssues []*github.Issue

	opts := &github.IssueListByRepoOptions{
		State:     "all",
		Sort:      "updated",
		Direction: "desc",
		Since:     since,
		ListOptions: github.ListOptions{
			PerPage: 100,
			Page:    1,
		},
	}

	for {
		pageCount := opts.Page
		if pageCount > 10 && pageCount%10 == 0 {
			log.Printf("Fetching page %d of issues for %s/%s...", pageCount, owner, name)
		}

		var issues []*github.Issue
		var err error

		operation := fmt.Sprintf("get issues page %d for %s/%s", pageCount, owner, name)
		retryErr := c.executeWithRetry(ctx, operation, func() (*github.Response, error) {
			var resp *github.Response
			issues, resp, err = c.client.Issues.ListByRepo(ctx, owner, name, opts)
			return resp, c.handleRateLimit(err, resp)
		})

		if retryErr != nil {
			return nil, fmt.Errorf("failed to get issues: %w", retryErr)
		}

		allIssues = append(allIssues, issues...)

		if len(issues) < opts.PerPage {
			break
		}
		opts.Page++
	}

	log.Printf("Fetched %d total issues for %s/%s", len(allIssues), owner, name)
	return allIssues, nil
}

// GetIssueComments gets comments for an issue
func (c *GitHubClient) GetIssueComments(ctx context.Context, owner, name string, issueNumber int) ([]*github.IssueComment, error) {
	var allComments []*github.IssueComment

	opts := &github.IssueListCommentsOptions{
		ListOptions: github.ListOptions{
			PerPage: 100,
			Page:    1,
		},
	}

	for {
		pageCount := opts.Page
		// Only log every 10 pages for issues with many comments
		// to avoid spamming the console in parallel mode

		var comments []*github.IssueComment
		var err error

		operation := fmt.Sprintf("get comments page %d for issue #%d in %s/%s", pageCount, issueNumber, owner, name)
		retryErr := c.executeWithRetry(ctx, operation, func() (*github.Response, error) {
			var resp *github.Response
			comments, resp, err = c.client.Issues.ListComments(ctx, owner, name, issueNumber, opts)
			return resp, c.handleRateLimit(err, resp)
		})

		if retryErr != nil {
			return nil, fmt.Errorf("failed to get comments: %w", retryErr)
		}

		allComments = append(allComments, comments...)

		if len(comments) < opts.PerPage {
			break
		}
		opts.Page++
	}

	// Only log if there are multiple pages of comments or a large number of comments
	if opts.Page > 2 || len(allComments) > 50 {
		log.Printf("Fetched %d comments for issue #%d in %s/%s", len(allComments), issueNumber, owner, name)
	}

	return allComments, nil
}

// ConvertGitHubRepository converts a GitHub repository to our model
func ConvertGitHubRepository(repo *github.Repository) *models.Repository {
	return &models.Repository{
		ID:       HandleGitHubID(repo.GetID()),
		Owner:    repo.GetOwner().GetLogin(),
		Name:     repo.GetName(),
		FullName: repo.GetFullName(),
	}
}

// ConvertGitHubUser converts a GitHub user to our model
func ConvertGitHubUser(user *github.User) *models.User {
	return &models.User{
		ID:        HandleGitHubID(user.GetID()),
		Login:     user.GetLogin(),
		AvatarURL: user.GetAvatarURL(),
		Type:      user.GetType(),
	}
}

// ConvertGitHubIssue converts a GitHub issue to our model
func ConvertGitHubIssue(issue *github.Issue) *models.Issue {
	var closedAt *time.Time
	if issue.ClosedAt != nil {
		t := issue.ClosedAt.Time
		closedAt = &t
	}

	var userID int64
	if issue.User != nil {
		userID = HandleGitHubID(issue.User.GetID())
	}

	return &models.Issue{
		ID:            HandleGitHubID(issue.GetID()),
		Number:        issue.GetNumber(),
		Title:         issue.GetTitle(),
		Body:          issue.GetBody(),
		State:         issue.GetState(),
		CreatedAt:     issue.GetCreatedAt().Time,
		UpdatedAt:     issue.GetUpdatedAt().Time,
		ClosedAt:      closedAt,
		UserID:        userID,
		IsPullRequest: issue.IsPullRequest(),
	}
}

// ConvertGitHubComment converts a GitHub comment to our model
func ConvertGitHubComment(comment *github.IssueComment, issueID int64) *models.Comment {
	var userID int64
	if comment.User != nil {
		userID = HandleGitHubID(comment.User.GetID())
	}

	return &models.Comment{
		ID:        HandleGitHubID(comment.GetID()),
		IssueID:   issueID,
		UserID:    userID,
		Body:      comment.GetBody(),
		CreatedAt: comment.GetCreatedAt().Time,
		UpdatedAt: comment.GetUpdatedAt().Time,
	}
}

// ConvertGitHubLabel converts a GitHub label to our model
func ConvertGitHubLabel(label *github.Label) *models.Label {
	return &models.Label{
		ID:    HandleGitHubID(*label.ID),
		Name:  *label.Name,
		Color: *label.Color,
	}
}

// HandleGitHubID ensures that large GitHub IDs are properly stored as int64
// by using string conversion to avoid overflow issues
func HandleGitHubID(id int64) int64 {
	// If the ID is already negative (which indicates it would overflow),
	// we'll convert it to a string and back to get the proper representation
	if id < 0 {
		// Convert to an unsigned representation, then back to int64
		unsignedID := uint64(id)
		idStr := strconv.FormatUint(unsignedID, 10)
		
		// Parse back to int64, ignoring any errors
		parsedID, _ := strconv.ParseInt(idStr, 10, 64)
		return parsedID
	}
	
	// If it's already positive, just return it
	return id
}
