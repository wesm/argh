package api

import (
	"context"
	"fmt"
	"net/http"
	"time"

	"github.com/google/go-github/v57/github"
	"github.com/wesm/github-issue-digest/internal/models"
	"golang.org/x/oauth2"
)

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

// GetRepository gets a repository by owner and name
func (c *GitHubClient) GetRepository(ctx context.Context, owner, name string) (*models.Repository, error) {
	repo, _, err := c.client.Repositories.Get(ctx, owner, name)
	if err != nil {
		return nil, fmt.Errorf("failed to get repository: %w", err)
	}

	return &models.Repository{
		ID:       repo.GetID(),
		Owner:    repo.GetOwner().GetLogin(),
		Name:     repo.GetName(),
		FullName: repo.GetFullName(),
	}, nil
}

// GetIssues gets issues for a repository, optionally since a specific time
func (c *GitHubClient) GetIssues(ctx context.Context, owner, name string, since time.Time) ([]*github.Issue, error) {
	var allIssues []*github.Issue
	opts := &github.IssueListByRepoOptions{
		State:     "all",
		Sort:      "updated",
		Direction: "desc",
		ListOptions: github.ListOptions{
			PerPage: 100,
		},
	}

	if !since.IsZero() {
		opts.Since = since
	}

	for {
		issues, resp, err := c.client.Issues.ListByRepo(ctx, owner, name, opts)
		if err != nil {
			return nil, fmt.Errorf("failed to list issues: %w", err)
		}

		allIssues = append(allIssues, issues...)

		if resp.NextPage == 0 {
			break
		}
		opts.Page = resp.NextPage
	}

	return allIssues, nil
}

// GetIssueComments gets comments for an issue
func (c *GitHubClient) GetIssueComments(ctx context.Context, owner, name string, issueNumber int) ([]*github.IssueComment, error) {
	var allComments []*github.IssueComment
	opts := &github.IssueListCommentsOptions{
		ListOptions: github.ListOptions{
			PerPage: 100,
		},
	}

	for {
		comments, resp, err := c.client.Issues.ListComments(ctx, owner, name, issueNumber, opts)
		if err != nil {
			return nil, fmt.Errorf("failed to list comments: %w", err)
		}

		allComments = append(allComments, comments...)

		if resp.NextPage == 0 {
			break
		}
		opts.Page = resp.NextPage
	}

	return allComments, nil
}

// ConvertGitHubUser converts a GitHub user to our model
func ConvertGitHubUser(user *github.User) *models.User {
	if user == nil {
		return nil
	}
	
	return &models.User{
		ID:        user.GetID(),
		Login:     user.GetLogin(),
		AvatarURL: user.GetAvatarURL(),
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
		userID = issue.User.GetID()
	}

	return &models.Issue{
		ID:            issue.GetID(),
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
		userID = comment.User.GetID()
	}

	return &models.Comment{
		ID:        comment.GetID(),
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
		ID:    *label.ID,
		Name:  *label.Name,
		Color: *label.Color,
	}
}
