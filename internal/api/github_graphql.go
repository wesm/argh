package api

import (
	"context"
	"fmt"
	"log"
	"strconv"
	"time"

	"github.com/shurcooL/githubv4"
	"github.com/wesm/github-issue-digest/internal/models"
	"golang.org/x/oauth2"
)

// GraphQLClient represents a client for the GitHub GraphQL API
type GraphQLClient struct {
	client *githubv4.Client
}

// NewGraphQLClient creates a new GraphQL client
func NewGraphQLClient(token string) *GraphQLClient {
	src := oauth2.StaticTokenSource(
		&oauth2.Token{AccessToken: token},
	)
	httpClient := oauth2.NewClient(context.Background(), src)
	client := githubv4.NewClient(httpClient)
	return &GraphQLClient{client: client}
}

// Repository represents a GitHub repository in GraphQL
type Repository struct {
	ID        githubv4.ID
	Name      githubv4.String
	Owner     struct {
		Login githubv4.String
	}
	NameWithOwner githubv4.String
}

// Actor represents a GitHub user in GraphQL
type Actor struct {
	Login     githubv4.String
	AvatarURL githubv4.String
	// Use inline fragments to access databaseId from different user types
	// We need to define fragments for all possible types that implement Actor interface
	UserDatabaseID  githubv4.Int `graphql:"... on User { databaseId }"`
	BotDatabaseID   githubv4.Int `graphql:"... on Bot { databaseId }"`
	MannequinDatabaseID githubv4.Int `graphql:"... on Mannequin { databaseId }"`
}

// getDatabaseID safely extracts the database ID from an Actor
func getDatabaseID(actor Actor) int64 {
	// Try different actor types
	if actor.UserDatabaseID > 0 {
		return int64(actor.UserDatabaseID)
	}
	if actor.BotDatabaseID > 0 {
		return int64(actor.BotDatabaseID)
	}
	if actor.MannequinDatabaseID > 0 {
		return int64(actor.MannequinDatabaseID)
	}
	
	// Fallback to hash of login if no ID found
	return generatePseudoID(string(actor.Login))
}

// Issue represents a GitHub issue in GraphQL
type Issue struct {
	ID        githubv4.ID
	Number    githubv4.Int
	Title     githubv4.String
	Body      githubv4.String
	State     githubv4.String
	CreatedAt githubv4.DateTime
	UpdatedAt githubv4.DateTime
	ClosedAt  *githubv4.DateTime
	Author    Actor
	// Use __typename to determine if this is a pull request
	// In the GitHub GraphQL API schema, both Issue and PullRequest share the same fields
	// but have different __typename values
	TypeName  githubv4.String `graphql:"__typename"`
	Comments struct {
		Nodes []Comment
		PageInfo struct {
			EndCursor   githubv4.String
			HasNextPage githubv4.Boolean
		}
	} `graphql:"comments(first: $commentsPerPage, after: $commentsEndCursor)"`
	Labels struct {
		Nodes []Label
	} `graphql:"labels(first: 50)"`
}

// Label represents a GitHub label in GraphQL
type Label struct {
	ID          githubv4.ID
	Name        githubv4.String
	Color       githubv4.String
	Description githubv4.String
}

// Comment represents a GitHub issue comment in GraphQL
type Comment struct {
	ID        githubv4.ID
	Body      githubv4.String
	CreatedAt githubv4.DateTime
	UpdatedAt githubv4.DateTime
	Author    Actor
}

// convertID converts a GitHub GraphQL ID to int64
func convertID(id githubv4.ID) int64 {
	// Convert githubv4.ID to a string, then parse to int64
	idStr := fmt.Sprintf("%v", id)
	// Try to parse the numeric part if it's a composite ID (e.g., "MDU6SXNzdWUyMzEzOTE1NTE=")
	// In some cases, we might need to use string IDs directly, but our models expect int64
	idInt, err := strconv.ParseInt(idStr, 10, 64)
	if err != nil {
		// If not a pure number, just hash it to get a numeric representation
		// This is not ideal but ensures we have an int64 ID for our models
		var hash int64
		for _, c := range idStr {
			hash = 31*hash + int64(c)
		}
		return hash
	}
	return idInt
}

// convertDateTime converts a githubv4.DateTime to time.Time
func convertDateTime(dt githubv4.DateTime) time.Time {
	// Use string conversion since direct type conversion doesn't work
	// Parse the RFC3339 string that GitHub API returns
	str := string(dt.String())
	t, err := time.Parse(time.RFC3339, str)
	if err != nil {
		// Fallback if parsing fails
		return time.Now()
	}
	return t
}

// convertNullableDateTime converts a pointer to githubv4.DateTime to a pointer to time.Time
func convertNullableDateTime(dt *githubv4.DateTime) *time.Time {
	if dt == nil {
		return nil
	}
	t := convertDateTime(*dt)
	return &t
}

// GetRepository gets a repository by owner and name
func (c *GraphQLClient) GetRepository(ctx context.Context, owner, name string) (*models.Repository, error) {
	var query struct {
		Repository Repository `graphql:"repository(owner: $owner, name: $name)"`
	}

	variables := map[string]interface{}{
		"owner": githubv4.String(owner),
		"name":  githubv4.String(name),
	}

	if err := c.client.Query(ctx, &query, variables); err != nil {
		return nil, fmt.Errorf("failed to query repository: %w", err)
	}

	return &models.Repository{
		ID:       convertID(query.Repository.ID),
		Owner:    string(query.Repository.Owner.Login),
		Name:     string(query.Repository.Name),
		FullName: string(query.Repository.NameWithOwner),
	}, nil
}

// IssueWithComments contains an issue and its comments
type IssueWithComments struct {
	Issue    *models.Issue
	Comments []*models.Comment
	Labels   []*models.Label
}

// GetIssuesWithComments gets issues with their comments for a repository
func (c *GraphQLClient) GetIssuesWithComments(ctx context.Context, owner, name string, since time.Time) ([]IssueWithComments, error) {
	var allIssuesWithComments []IssueWithComments
	
	// Variables for pagination
	var issuesEndCursor *githubv4.String
	hasMoreIssues := true
	
	for hasMoreIssues {
		issues, hasNext, endCursor, err := c.fetchIssuesBatch(ctx, owner, name, since, issuesEndCursor)
		if err != nil {
			return nil, err
		}
		
		allIssuesWithComments = append(allIssuesWithComments, issues...)
		hasMoreIssues = hasNext
		issuesEndCursor = endCursor
		
		// Periodically log progress
		if len(allIssuesWithComments) > 0 && (len(allIssuesWithComments)%100 == 0 || !hasMoreIssues) {
			log.Printf("Fetched %d issues so far for %s/%s", len(allIssuesWithComments), owner, name)
		}
	}
	
	return allIssuesWithComments, nil
}

// fetchIssuesBatch fetches a batch of issues with comments
func (c *GraphQLClient) fetchIssuesBatch(
	ctx context.Context, 
	owner, name string, 
	since time.Time, 
	afterCursor *githubv4.String,
) ([]IssueWithComments, bool, *githubv4.String, error) {
	var query struct {
		RateLimit struct {
			Limit     githubv4.Int
			Cost      githubv4.Int
			Remaining githubv4.Int
			ResetAt   githubv4.DateTime
		}
		Repository struct {
			Issues struct {
				Nodes    []Issue
				PageInfo struct {
					EndCursor   githubv4.String
					HasNextPage githubv4.Boolean
				}
			} `graphql:"issues(first: $issuesPerPage, after: $issuesEndCursor, orderBy: {field: UPDATED_AT, direction: DESC})"`
		} `graphql:"repository(owner: $owner, name: $name)"`
	}

	variables := map[string]interface{}{
		"owner":             githubv4.String(owner),
		"name":              githubv4.String(name),
		"issuesPerPage":     githubv4.Int(50),
		"issuesEndCursor":   afterCursor,
		"commentsPerPage":   githubv4.Int(50),
		"commentsEndCursor": (*githubv4.String)(nil), // Start with first page of comments
	}

	if err := c.client.Query(ctx, &query, variables); err != nil {
		return nil, false, nil, fmt.Errorf("failed to query issues: %w", err)
	}

	// Check rate limit and log
	remaining := int(query.RateLimit.Remaining)
	if remaining < 1000 {
		resetAt := convertDateTime(query.RateLimit.ResetAt)
		log.Printf("GraphQL rate limit status: %d/%d remaining, resets at %s", 
			remaining, int(query.RateLimit.Limit), resetAt.Format(time.RFC3339))
	}

	// Convert to our domain models
	var result []IssueWithComments
	for _, issue := range query.Repository.Issues.Nodes {
		// Skip issues that haven't been updated since the last sync
		if convertDateTime(issue.UpdatedAt).Before(since) {
			continue
		}

		// First get or create the user for this issue
		var userID int64
		userID = getDatabaseID(issue.Author)

		// Convert issue
		modelIssue := &models.Issue{
			ID:            convertID(issue.ID),
			Number:        int(issue.Number),
			Title:         string(issue.Title),
			Body:          string(issue.Body),
			State:         string(issue.State),
			CreatedAt:     convertDateTime(issue.CreatedAt),
			UpdatedAt:     convertDateTime(issue.UpdatedAt),
			ClosedAt:      convertNullableDateTime(issue.ClosedAt),
			UserID:        userID,
			// Check the __typename to determine if this is a pull request
			IsPullRequest: string(issue.TypeName) == "PullRequest",
		}

		// Convert comments
		var modelComments []*models.Comment
		var usersToSave []*models.User
		
		for _, comment := range issue.Comments.Nodes {
			var commentUserID int64
			commentUserID = getDatabaseID(comment.Author)

			commentUser := &models.User{
				ID:        commentUserID,
				Login:     string(comment.Author.Login),
				AvatarURL: string(comment.Author.AvatarURL),
			}
			usersToSave = append(usersToSave, commentUser)
			
			modelComment := &models.Comment{
				ID:        convertID(comment.ID),
				IssueID:   modelIssue.ID, // Will be set when the issue is saved
				UserID:    commentUserID,
				Body:      string(comment.Body),
				CreatedAt: convertDateTime(comment.CreatedAt),
				UpdatedAt: convertDateTime(comment.UpdatedAt),
			}
			modelComments = append(modelComments, modelComment)
		}

		// Convert labels
		var modelLabels []*models.Label
		for _, label := range issue.Labels.Nodes {
			modelLabel := &models.Label{
				ID:    convertID(label.ID),
				Name:  string(label.Name),
				Color: string(label.Color),
			}
			modelLabels = append(modelLabels, modelLabel)
		}

		// Fetch additional comments if there are more pages
		if bool(issue.Comments.PageInfo.HasNextPage) {
			additionalComments, additionalUsers, err := c.fetchAdditionalComments(
				ctx, owner, name, int(issue.Number), modelIssue.ID, issue.Comments.PageInfo.EndCursor)
			if err != nil {
				log.Printf("Warning: Failed to fetch additional comments for issue #%d: %v", 
					int(issue.Number), err)
			} else {
				modelComments = append(modelComments, additionalComments...)
				usersToSave = append(usersToSave, additionalUsers...)
			}
		}

		// Add to results
		result = append(result, IssueWithComments{
			Issue:    modelIssue,
			Comments: modelComments,
			Labels:   modelLabels,
		})
	}

	endCursor := &query.Repository.Issues.PageInfo.EndCursor
	if !bool(query.Repository.Issues.PageInfo.HasNextPage) {
		endCursor = nil
	}

	return result, bool(query.Repository.Issues.PageInfo.HasNextPage), endCursor, nil
}

// fetchAdditionalComments fetches additional pages of comments for an issue
func (c *GraphQLClient) fetchAdditionalComments(
	ctx context.Context,
	owner, name string,
	issueNumber int,
	issueID int64,
	afterCursor githubv4.String,
) ([]*models.Comment, []*models.User, error) {
	var allComments []*models.Comment
	var allUsers []*models.User
	hasMoreComments := true
	currentCursor := afterCursor

	for hasMoreComments {
		var query struct {
			Repository struct {
				Issue struct {
					Comments struct {
						Nodes []Comment
						PageInfo struct {
							EndCursor   githubv4.String
							HasNextPage githubv4.Boolean
						}
					} `graphql:"comments(first: $commentsPerPage, after: $commentsEndCursor)"`
				} `graphql:"issue(number: $issueNumber)"`
			} `graphql:"repository(owner: $owner, name: $name)"`
		}

		variables := map[string]interface{}{
			"owner":             githubv4.String(owner),
			"name":              githubv4.String(name),
			"issueNumber":       githubv4.Int(issueNumber),
			"commentsPerPage":   githubv4.Int(100),
			"commentsEndCursor": currentCursor,
		}

		if err := c.client.Query(ctx, &query, variables); err != nil {
			return allComments, allUsers, fmt.Errorf("failed to query additional comments: %w", err)
		}

		// Convert and append comments
		for _, comment := range query.Repository.Issue.Comments.Nodes {
			var commentUserID int64
			commentUserID = getDatabaseID(comment.Author)

			commentUser := &models.User{
				ID:        commentUserID,
				Login:     string(comment.Author.Login),
				AvatarURL: string(comment.Author.AvatarURL),
			}
			allUsers = append(allUsers, commentUser)
			
			modelComment := &models.Comment{
				ID:        convertID(comment.ID),
				IssueID:   issueID,
				UserID:    commentUserID,
				Body:      string(comment.Body),
				CreatedAt: convertDateTime(comment.CreatedAt),
				UpdatedAt: convertDateTime(comment.UpdatedAt),
			}
			allComments = append(allComments, modelComment)
		}

		// Update pagination
		hasMoreComments = bool(query.Repository.Issue.Comments.PageInfo.HasNextPage)
		if hasMoreComments {
			currentCursor = query.Repository.Issue.Comments.PageInfo.EndCursor
		}
	}

	return allComments, allUsers, nil
}

// generatePseudoID creates a numeric ID from a string
func generatePseudoID(s string) int64 {
	// Simple hash function to generate a pseudo-ID
	var hash int64 = 0
	for _, c := range s {
		hash = hash*31 + int64(c)
	}
	return hash
}
