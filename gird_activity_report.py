#!/usr/bin/env python3
"""
GitHub Activity Report Generator

This script queries the SQLite database created by GIRD (GitHub Issues Repo Database)
to generate activity reports for a specific time range. The report can be sent to
Claude AI via the chatlas package for summarization.
"""

import argparse
import datetime
import json
import os
import sqlite3
from typing import Dict, List, Optional, Tuple, Union

import chatlas

# Default configuration
DEFAULT_DB_PATH = "github_issues.db"
DEFAULT_DAYS = 7  # Default time range in days


class GirdDatabase:
    """Class to interact with the GIRD SQLite database."""

    def __init__(self, db_path: str):
        """Initialize database connection.
        
        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        # Enable row factory to get results as dictionaries
        self.conn.row_factory = sqlite3.Row

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.conn.close()

    def get_recent_activity(
        self, start_date: datetime.datetime, end_date: datetime.datetime, repos: Optional[List[str]] = None
    ) -> Dict[str, List[Dict]]:
        """Get all GitHub activity between start_date and end_date.
        
        Args:
            start_date: Start date for the activity window
            end_date: End date for the activity window
            repos: Optional list of repository names to filter by (format: "owner/name")
            
        Returns:
            Dictionary with keys 'issues', 'pull_requests', and 'comments', each containing
            a list of corresponding activity items.
        """
        cursor = self.conn.cursor()
        
        repo_filter = ""
        repo_params = []
        
        if repos:
            repo_placeholders = ",".join("?" for _ in repos)
            repo_filter = f"AND repositories.full_name IN ({repo_placeholders})"
            repo_params = repos
        
        # Format dates for SQLite
        start_date_str = start_date.strftime("%Y-%m-%d %H:%M:%S")
        end_date_str = end_date.strftime("%Y-%m-%d %H:%M:%S")
        
        # Query new issues and PRs
        issues_query = f"""
        SELECT 
            issues.id,
            issues.number,
            issues.title,
            issues.body,
            issues.state,
            issues.created_at,
            issues.updated_at,
            issues.closed_at,
            issues.is_pull_request,
            users.login as user_login,
            repositories.full_name as repository
        FROM 
            issues
        JOIN 
            repositories ON issues.repository_id = repositories.id
        JOIN 
            users ON issues.user_id = users.id
        WHERE 
            issues.created_at BETWEEN ? AND ?
            {repo_filter}
        ORDER BY 
            issues.created_at DESC
        """
        
        cursor.execute(issues_query, [start_date_str, end_date_str] + repo_params)
        all_issues = [dict(row) for row in cursor.fetchall()]
        
        # Query new comments
        comments_query = f"""
        SELECT 
            comments.id,
            comments.body,
            comments.created_at,
            comments.updated_at,
            users.login as user_login,
            issues.number as issue_number,
            issues.title as issue_title,
            issues.is_pull_request,
            repositories.full_name as repository
        FROM 
            comments
        JOIN 
            issues ON comments.issue_id = issues.id
        JOIN 
            repositories ON issues.repository_id = repositories.id
        JOIN 
            users ON comments.user_id = users.id
        WHERE 
            comments.created_at BETWEEN ? AND ?
            {repo_filter}
        ORDER BY 
            comments.created_at DESC
        """
        
        cursor.execute(comments_query, [start_date_str, end_date_str] + repo_params)
        all_comments = [dict(row) for row in cursor.fetchall()]
        
        # Separate issues and pull requests
        issues = [issue for issue in all_issues if not issue["is_pull_request"]]
        pull_requests = [pr for pr in all_issues if pr["is_pull_request"]]
        
        return {
            "issues": issues,
            "pull_requests": pull_requests,
            "comments": all_comments
        }
    
    def get_repository_names(self) -> List[str]:
        """Get the list of repository names in the database.
        
        Returns:
            List of repository names in "owner/name" format
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT full_name FROM repositories ORDER BY full_name")
        return [row["full_name"] for row in cursor.fetchall()]


def format_activity_for_claude(activity: Dict[str, List[Dict]]) -> str:
    """Format the activity data for Claude AI consumption.
    
    Args:
        activity: Activity dictionary with issues, PRs and comments
        
    Returns:
        Formatted markdown text suitable for sending to Claude
    """
    issues = activity["issues"]
    pull_requests = activity["pull_requests"]
    comments = activity["comments"]
    
    output = []
    
    # Format issues
    if issues:
        output.append("## New Issues")
        for issue in issues:
            output.append(f"### #{issue['number']} - {issue['title']}")
            output.append(f"**Author:** {issue['user_login']}")
            output.append(f"**Repository:** {issue['repository']}")
            output.append(f"**Created:** {issue['created_at']}")
            output.append(f"**State:** {issue['state']}")
            output.append("\n**Description:**")
            output.append(issue["body"] if issue["body"] else "(No description)")
            output.append("\n" + "-" * 50 + "\n")
    
    # Format pull requests
    if pull_requests:
        output.append("## New Pull Requests")
        for pr in pull_requests:
            output.append(f"### #{pr['number']} - {pr['title']}")
            output.append(f"**Author:** {pr['user_login']}")
            output.append(f"**Repository:** {pr['repository']}")
            output.append(f"**Created:** {pr['created_at']}")
            output.append(f"**State:** {pr['state']}")
            output.append("\n**Description:**")
            output.append(pr["body"] if pr["body"] else "(No description)")
            output.append("\n" + "-" * 50 + "\n")
    
    # Format comments
    if comments:
        output.append("## New Comments")
        for comment in comments:
            issue_or_pr = "PR" if comment["is_pull_request"] else "Issue"
            output.append(f"### Comment on {issue_or_pr} #{comment['issue_number']} - {comment['issue_title']}")
            output.append(f"**Author:** {comment['user_login']}")
            output.append(f"**Repository:** {comment['repository']}")
            output.append(f"**Created:** {comment['created_at']}")
            output.append("\n**Comment:**")
            output.append(comment["body"] if comment["body"] else "(Empty comment)")
            output.append("\n" + "-" * 50 + "\n")
    
    return "\n".join(output)


def send_to_claude(content: str, api_key: str, prompt: str = None) -> str:
    """Send the activity report to Claude and get a summary.
    
    Args:
        content: The formatted activity data
        api_key: Claude API key
        prompt: Custom prompt for Claude
        
    Returns:
        Claude's response
    """
    # Initialize chatlas with your API key
    client = chatlas.Client(api_key)
    
    # Default prompt if none provided
    if not prompt:
        prompt = """
        Please review this GitHub activity report and provide a concise summary.
        Highlight the most important issues, pull requests, and discussions.
        Group related items together and identify key themes or areas of focus.
        """
    
    # Create a message with the activity data and prompt
    message = f"{prompt}\n\n{content}"
    
    # Send to Claude and get the response
    response = client.send_message(message)
    
    return response.content


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Generate GitHub activity reports from GIRD database")
    parser.add_argument("--db", type=str, default=DEFAULT_DB_PATH, help=f"Path to the GIRD SQLite database (default: {DEFAULT_DB_PATH})")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help=f"Number of days to look back (default: {DEFAULT_DAYS})")
    parser.add_argument("--start-date", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--repos", type=str, nargs="*", help="Specific repositories to filter by (owner/name format)")
    parser.add_argument("--list-repos", action="store_true", help="List all repositories in the database")
    parser.add_argument("--output", type=str, help="Output file for the report (default: stdout)")
    parser.add_argument("--claude", action="store_true", help="Send the report to Claude for summarization")
    parser.add_argument("--claude-key", type=str, help="Claude API key")
    parser.add_argument("--claude-prompt", type=str, help="Custom prompt for Claude")
    
    return parser.parse_args()


def main():
    """Main function."""
    args = parse_args()
    
    # Open database connection
    with GirdDatabase(args.db) as db:
        
        # List repositories if requested
        if args.list_repos:
            repos = db.get_repository_names()
            print("Repositories in database:")
            for repo in repos:
                print(f"  - {repo}")
            return
        
        # Determine date range
        end_date = datetime.datetime.now()
        if args.end_date:
            end_date = datetime.datetime.strptime(args.end_date, "%Y-%m-%d")
        
        start_date = end_date - datetime.timedelta(days=args.days)
        if args.start_date:
            start_date = datetime.datetime.strptime(args.start_date, "%Y-%m-%d")
        
        # Get activity data
        activity = db.get_recent_activity(start_date, end_date, args.repos)
        
        # Format for output
        formatted_report = format_activity_for_claude(activity)
        
        # Output the report
        if args.output:
            with open(args.output, "w") as f:
                f.write(formatted_report)
            print(f"Report written to {args.output}")
        else:
            print(formatted_report)
        
        # Send to Claude if requested
        if args.claude:
            if not args.claude_key:
                claude_key = os.environ.get("CLAUDE_API_KEY")
                if not claude_key:
                    print("Error: Claude API key not provided. Use --claude-key or set CLAUDE_API_KEY environment variable.")
                    return
            else:
                claude_key = args.claude_key
            
            # Send to Claude and print response
            claude_response = send_to_claude(formatted_report, claude_key, args.claude_prompt)
            print("\n--- Claude Summary ---\n")
            print(claude_response)


if __name__ == "__main__":
    main()
