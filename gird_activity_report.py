#!/usr/bin/env python3

"""
GitHub Activity Report Generator for GIRD

Generates reports for recent GitHub activity from a GIRD database.

This script analyzes GitHub issue and pull request activity stored in a GIRD SQLite database
and generates a detailed Markdown report that can be:
1. Viewed directly as plain text
2. Sent to an LLM (Anthropic's Claude or OpenAI) for summarization

Features:
- Filter activity by date range
- Filter by specific repositories
- Generate summaries using Claude 3.7 Sonnet (default) or OpenAI models
- Markdown formatting with proper GitHub links

Usage:
  python gird_activity_report.py [OPTIONS]

Examples:
  # Generate a report for the last 7 days and print to console
  python gird_activity_report.py

  # Generate a report with OpenAI and save to file
  python gird_activity_report.py --llm-provider openai --output report.md

  # Generate a report for specific repositories for the last 14 days
  python gird_activity_report.py --days 14 --repositories "owner/repo1,owner/repo2"

Requirements:
  - A GIRD SQLite database (github_issues.db by default)
  - chatlas Python package for LLM integration (pip install chatlas)
  - API key for Anthropic or OpenAI
"""

import os
import re
import datetime
import sqlite3
from typing import Dict, List, Optional
import click

# Try to import chatlas components
CHATLAS_AVAILABLE = False
ANTHROPIC_AVAILABLE = False
OPENAI_AVAILABLE = False

try:
    from chatlas import ChatAnthropic
    ANTHROPIC_AVAILABLE = True
    CHATLAS_AVAILABLE = True
except ImportError:
    pass

try:
    from chatlas import ChatOpenAI
    OPENAI_AVAILABLE = True
    CHATLAS_AVAILABLE = True
except ImportError:
    pass

if not CHATLAS_AVAILABLE:
    print("Warning: chatlas package not found. Install with: pip install chatlas")
    print("Continuing in case you're just using --dry-run...")

# Constants
DEFAULT_DB_PATH = "github_issues.db"
DEFAULT_DAYS = 7
MAX_LINE_WIDTH = 90  # Maximum width for text wrapping

def wrap_text(text, width=MAX_LINE_WIDTH):
    """
    Wrap text to fit within specified width while preserving Markdown formatting.
    
    Args:
        text: Text to wrap
        width: Maximum width for each line (default: MAX_LINE_WIDTH)
        
    Returns:
        Wrapped text
    """
    # Don't wrap if text is None or empty
    if not text:
        return text
        
    lines = text.split('\n')
    wrapped_lines = []
    
    for line in lines:
        # Skip wrapping for code blocks, tables, and other special Markdown elements
        if line.startswith('```') or line.startswith('|') or line.startswith('#') or \
           line.startswith('- ') or line.startswith('* ') or line.startswith('> ') or \
           line.strip() == '---' or line.strip() == '':
            wrapped_lines.append(line)
            continue
            
        # Wrap the line
        current_width = 0
        wrapped_line = []
        words = line.split(' ')
        
        for word in words:
            if current_width + len(word) + 1 > width and current_width > 0:
                wrapped_lines.append(' '.join(wrapped_line))
                wrapped_line = [word]
                current_width = len(word)
            else:
                wrapped_line.append(word)
                current_width += len(word) + 1
                
        if wrapped_line:
            wrapped_lines.append(' '.join(wrapped_line))
            
    return '\n'.join(wrapped_lines)

def format_date(date_str):
    """
    Format a date string from ISO format to a more readable format.
    
    Args:
        date_str: ISO format date string (e.g. "2023-04-25T15:30:15Z")
        
    Returns:
        Formatted date string (e.g. "Apr 25, 2023")
    """
    try:
        # Parse ISO format date
        date_obj = datetime.datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        # Format to a more readable format
        return date_obj.strftime("%b %d, %Y")
    except (ValueError, AttributeError):
        # Return the original string if parsing fails
        return date_str

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
        self,
        start_date: datetime.datetime,
        end_date: datetime.datetime,
        repos: Optional[List[str]] = None,
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
            # For each repository name in format "owner/name", we'll filter by
            # comparing with repositories.full_name
            placeholder_list = []
            for _ in repos:
                placeholder_list.append("?")

            if placeholder_list:
                placeholders = ", ".join(placeholder_list)
                repo_filter = f" AND repositories.full_name IN ({placeholders})"
                repo_params = repos

        # Format dates for SQLite
        start_date_str = start_date.strftime("%Y-%m-%d %H:%M:%S")
        end_date_str = end_date.strftime("%Y-%m-%d %H:%M:%S")

        # Query new issues and PRs
        issues_query = (
            """
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
            issues.created_at >= ? AND issues.created_at <= ?
            """
            + repo_filter
            + """
        ORDER BY 
            issues.created_at DESC
        """
        )

        cursor.execute(issues_query, [start_date_str, end_date_str] + repo_params)
        all_issues = [dict(row) for row in cursor.fetchall()]

        # Query new comments
        comments_query = (
            """
        SELECT 
            comments.id,
            comments.body,
            comments.created_at,
            comments.updated_at,
            users.login as user_login,
            issues.number as issue_number,
            issues.title as issue_title,
            issues.is_pull_request,
            repositories.full_name as repository,
            issues.id as issue_id
        FROM 
            comments
        JOIN 
            issues ON comments.issue_id = issues.id
        JOIN 
            repositories ON issues.repository_id = repositories.id
        JOIN 
            users ON comments.user_id = users.id
        WHERE 
            comments.created_at >= ? AND comments.created_at <= ?
            """
            + repo_filter
            + """
        ORDER BY 
            comments.created_at DESC
        """
        )

        cursor.execute(comments_query, [start_date_str, end_date_str] + repo_params)
        all_comments = [dict(row) for row in cursor.fetchall()]

        # Separate issues and pull requests
        issues = [issue for issue in all_issues if not issue["is_pull_request"]]
        pull_requests = [pr for pr in all_issues if pr["is_pull_request"]]

        return {
            "issues": issues,
            "pull_requests": pull_requests,
            "comments": all_comments,
        }

    def get_repository_names(self) -> List[str]:
        """Get the list of repository names in the database.

        Returns:
            List of repository names in "owner/name" format
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT full_name FROM repositories ORDER BY full_name")
        return [row["full_name"] for row in cursor.fetchall()]

    def get_top_contributors(
        self,
        start_date: datetime.datetime,
        end_date: datetime.datetime,
        repos: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[Dict]:
        """Get top contributors based on activity within the date range.

        Args:
            start_date: Start date for the activity window
            end_date: End date for the activity window
            repos: Optional list of repository names to filter by
            limit: Maximum number of contributors to return

        Returns:
            List of dictionaries with contributor information, sorted by activity count
        """
        cursor = self.conn.cursor()

        repo_filter = ""
        repo_params = []

        if repos:
            repo_placeholders = ",".join("?" for _ in repos)
            repo_filter = "AND repositories.full_name IN (" + repo_placeholders + ")"
            repo_params = repos

        # Format dates for SQLite
        start_date_str = start_date.strftime("%Y-%m-%d %H:%M:%S")
        end_date_str = end_date.strftime("%Y-%m-%d %H:%M:%S")

        # SQLite doesn't support FULL OUTER JOIN, so we need to use LEFT JOIN + UNION
        query = (
            """
        -- Contributors from issues and PRs
        WITH issue_creators AS (
            SELECT 
                users.id as user_id,
                users.login as user_login,
                users.type as user_type,
                SUM(CASE WHEN issues.is_pull_request = 0 THEN 1 ELSE 0 END) as issue_count,
                SUM(CASE WHEN issues.is_pull_request = 1 THEN 1 ELSE 0 END) as pr_count,
                0 as comment_count
            FROM 
                issues
            JOIN 
                repositories ON issues.repository_id = repositories.id
            JOIN 
                users ON issues.user_id = users.id
            WHERE 
                issues.created_at >= ? AND issues.created_at <= ?
                """
            + repo_filter
            + """
            GROUP BY 
                users.id, users.login, users.type
        ),
        -- Contributors from comments
        commenters AS (
            SELECT 
                users.id as user_id,
                users.login as user_login,
                users.type as user_type,
                0 as issue_count,
                0 as pr_count,
                COUNT(*) as comment_count
            FROM 
                comments
            JOIN 
                issues ON comments.issue_id = issues.id
            JOIN 
                repositories ON issues.repository_id = repositories.id
            JOIN 
                users ON comments.user_id = users.id
            WHERE 
                comments.created_at >= ? AND comments.created_at <= ?
                """
            + repo_filter
            + """
            GROUP BY 
                users.id, users.login, users.type
        ),
        -- Combine both contribution types
        all_contributors AS (
            SELECT * FROM issue_creators
            UNION ALL
            SELECT * FROM commenters
        )
        -- Aggregate the contributions by user
        SELECT 
            user_id,
            user_login,
            user_type,
            SUM(issue_count) as issue_count,
            SUM(pr_count) as pr_count,
            SUM(comment_count) as comment_count,
            SUM(issue_count + pr_count + comment_count) as total_activity
        FROM 
            all_contributors
        WHERE
            user_type = 'User'
        GROUP BY 
            user_id, user_login, user_type
        ORDER BY 
            total_activity DESC
        LIMIT ?
        """
        )

        cursor.execute(
            query,
            [start_date_str, end_date_str]
            + repo_params
            + [start_date_str, end_date_str]
            + repo_params
            + [limit],
        )

        return [dict(row) for row in cursor.fetchall()]

    def get_hot_issues(
        self,
        start_date: datetime.datetime,
        end_date: datetime.datetime,
        repos: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[Dict]:
        """Get issues/PRs with the most activity within the date range.

        Args:
            start_date: Start date for the activity window
            end_date: End date for the activity window
            repos: Optional list of repository names to filter by
            limit: Maximum number of hot issues to return

        Returns:
            List of dictionaries with issue information, sorted by activity count
        """
        cursor = self.conn.cursor()

        repo_filter = ""
        repo_params = []

        if repos:
            # For each repository name in format "owner/name", we'll filter by
            # comparing with repositories.full_name column
            placeholder_list = []
            for _ in repos:
                placeholder_list.append("?")

            if placeholder_list:
                placeholders = ", ".join(placeholder_list)
                repo_filter = f" AND r.full_name IN ({placeholders})"
                repo_params = repos

        # Format dates for SQLite
        start_date_str = start_date.strftime("%Y-%m-%d")
        end_date_str = end_date.strftime("%Y-%m-%d")

        # Query for issues with most comments in the time period
        query = (
            """
        SELECT 
            i.id as issue_id,
            i.number as issue_number,
            i.title as issue_title,
            i.state as issue_state,
            i.created_at as issue_created_at,
            i.updated_at as issue_updated_at,
            i.is_pull_request,
            u.login as creator_login,
            r.full_name as repository,
            COUNT(c.id) as comment_count,
            i.body as description
        FROM 
            issues i
        JOIN 
            repositories r ON i.repository_id = r.id
        JOIN 
            users u ON i.user_id = u.id
        LEFT JOIN 
            comments c ON i.id = c.issue_id AND c.created_at BETWEEN ? AND ?
        WHERE 
            (i.created_at BETWEEN ? AND ? OR i.updated_at BETWEEN ? AND ?)
            """
            + repo_filter
            + """
        GROUP BY 
            i.id
        ORDER BY 
            comment_count DESC, i.updated_at DESC
        LIMIT ?
        """
        )

        cursor.execute(
            query,
            [
                start_date_str,
                end_date_str,
                start_date_str,
                end_date_str,
                start_date_str,
                end_date_str,
            ]
            + repo_params
            + [limit],
        )

        return [dict(row) for row in cursor.fetchall()]

    def chunk_activity_by_time(self, activity, days_per_chunk):
        """
        Split activity data into time-based chunks.

        Args:
            activity (dict): Activity data dictionary with issues, prs and comments
            days_per_chunk (int): Number of days for each chunk

        Returns:
            list: List of dictionaries with start_date, end_date, and data for each chunk
        """
        if not activity or not (
            activity.get("issues")
            or activity.get("pull_requests")
            or activity.get("comments")
        ):
            return []

        # Find the overall date range from the activity data
        all_dates = []

        for issue in activity.get("issues", []):
            all_dates.append(
                datetime.datetime.strptime(issue["created_at"], "%Y-%m-%dT%H:%M:%SZ")
            )

        for pr in activity.get("pull_requests", []):
            all_dates.append(
                datetime.datetime.strptime(pr["created_at"], "%Y-%m-%dT%H:%M:%SZ")
            )

        for comment in activity.get("comments", []):
            all_dates.append(
                datetime.datetime.strptime(comment["created_at"], "%Y-%m-%dT%H:%M:%SZ")
            )

        if not all_dates:
            return []

        # Calculate the global date range
        global_start = min(all_dates)
        global_end = max(all_dates)

        # Calculate number of chunks
        total_days = (global_end - global_start).days + 1
        num_chunks = (
            total_days + days_per_chunk - 1
        ) // days_per_chunk  # Ceiling division

        chunks = []
        for i in range(num_chunks):
            chunk_start = global_start + datetime.timedelta(days=i * days_per_chunk)
            chunk_end = min(
                global_start + datetime.timedelta(days=(i + 1) * days_per_chunk - 1),
                global_end,
            )

            # Filter activity for this chunk
            chunk_data = {"issues": [], "pull_requests": [], "comments": []}

            for issue in activity.get("issues", []):
                issue_date = datetime.datetime.strptime(
                    issue["created_at"], "%Y-%m-%dT%H:%M:%SZ"
                )
                if chunk_start <= issue_date <= chunk_end:
                    chunk_data["issues"].append(issue)

            for pr in activity.get("pull_requests", []):
                pr_date = datetime.datetime.strptime(
                    pr["created_at"], "%Y-%m-%dT%H:%M:%SZ"
                )
                if chunk_start <= pr_date <= chunk_end:
                    chunk_data["pull_requests"].append(pr)

            for comment in activity.get("comments", []):
                comment_date = datetime.datetime.strptime(
                    comment["created_at"], "%Y-%m-%dT%H:%M:%SZ"
                )
                if chunk_start <= comment_date <= chunk_end:
                    chunk_data["comments"].append(comment)

            # Only add chunk if it has any activity
            if (
                chunk_data["issues"]
                or chunk_data["pull_requests"]
                or chunk_data["comments"]
            ):
                chunks.append(
                    {
                        "start_date": chunk_start,
                        "end_date": chunk_end,
                        "data": chunk_data,
                    }
                )

        return chunks


def chunk_report_for_llm(report, max_chars=20000):
    """
    Split a large report into smaller chunks for LLM processing, trying to maintain section integrity.

    Args:
        report (str): Full markdown report text
        max_chars (int): Maximum characters per chunk (default: 20000)

    Returns:
        list: List of report chunks
    """
    # If report is under the limit, return it as a single chunk
    if len(report) <= max_chars:
        return [report]

    # Split the report by major section headers
    sections = re.split(r"(^# .*$)", report, flags=re.MULTILINE)

    # First element will be empty if the report starts with a header
    if sections and not sections[0].strip():
        sections.pop(0)

    chunks = []
    current_chunk = ""

    # Process each section
    i = 0
    while i < len(sections):
        # If this is a section header
        if i % 2 == 0 and i + 1 < len(sections):
            header = sections[i]
            content = sections[i + 1]

            # If adding this section would exceed the limit, start a new chunk
            if len(current_chunk) + len(header) + len(content) > max_chars:
                # If the current chunk has content, append it to chunks
                if current_chunk:
                    chunks.append(current_chunk)

                # Start a new chunk with this section
                current_chunk = header + content

                # If this single section is too big, split it by subsections
                if len(current_chunk) > max_chars:
                    subsections = re.split(r"(^## .*$)", content, flags=re.MULTILINE)

                    # First element will be empty or extra content if content doesn't start with ##
                    current_chunk = header
                    if subsections[0].strip():
                        current_chunk += subsections[0]

                    # Process subsections
                    j = 1
                    while j < len(subsections):
                        if j % 2 == 1 and j + 1 < len(
                            subsections
                        ):  # This is a subsection header
                            subheader = subsections[j]
                            subcontent = subsections[j + 1]

                            # If adding this subsection would exceed limit, start a new chunk
                            if (
                                len(current_chunk) + len(subheader) + len(subcontent)
                                > max_chars
                            ):
                                chunks.append(current_chunk)
                                current_chunk = (
                                    header + " (continued)\n\n" + subheader + subcontent
                                )
                            else:
                                current_chunk += subheader + subcontent

                            j += 2
                        else:
                            # Handle any remaining content
                            if j < len(subsections):
                                current_chunk += subsections[j]
                            j += 1

                    # If we have a non-empty current chunk, add it
                    if current_chunk.strip():
                        chunks.append(current_chunk)
                        current_chunk = ""
            else:
                # This section fits in the current chunk
                current_chunk += header + content

            i += 2
        else:
            # Handle any content not paired with a header
            if i < len(sections):
                if len(current_chunk) + len(sections[i]) > max_chars:
                    chunks.append(current_chunk)
                    current_chunk = sections[i]
                else:
                    current_chunk += sections[i]
            i += 1

    # Add the final chunk if it has content
    if current_chunk.strip():
        chunks.append(current_chunk)

    return chunks


def format_activity_for_report(
    activity,
    start_date=None,
    end_date=None,
):
    """
    Format the activity data for LLM consumption.

    Args:
        activity: Activity dictionary with issues, prs and comments
        start_date: Start date of the report period
        end_date: End date of the report period

    Returns:
        Formatted markdown text suitable for sending to an LLM
    """
    issues = activity.get("issues", [])
    prs = activity.get("pull_requests", [])
    comments = activity.get("comments", [])

    output = []

    # Add report header with date range
    if start_date and end_date:
        # Format the date range more accurately
        # If dates are within the same month and year
        if start_date.year == end_date.year and start_date.month == end_date.month:
            output.append(
                f"# GitHub Activity Report: {start_date.strftime('%B %d')} - {end_date.strftime('%d, %Y')}"
            )
        # If dates are in the same year but different months
        elif start_date.year == end_date.year:
            output.append(
                f"# GitHub Activity Report: {start_date.strftime('%B %d')} - {end_date.strftime('%B %d, %Y')}"
            )
        # If dates are in different years
        else:
            output.append(
                f"# GitHub Activity Report: {start_date.strftime('%B %d, %Y')} - {end_date.strftime('%B %d, %Y')}"
            )
    else:
        output.append("# GitHub Activity Report")

    output.append("\n## Executive Summary")
    output.append("- **Issues Created:** " + str(len(issues)))
    output.append("- **Pull Requests Created:** " + str(len(prs)))
    output.append("- **Comments Added:** " + str(len(comments)))

    # Add repository stats if we have them
    repos = set()
    for item in issues + prs:
        if "repository" in item:
            repos.add(item["repository"])

    if repos:
        output.append("- **Repositories:** " + str(len(repos)))
        output.append("  - " + ", ".join(sorted(repos)))

    # Format issues with GitHub links
    if issues:
        output.append("\n## New Issues")
        for issue in issues:
            repo = issue.get("repository", "unknown/repo")
            number = issue.get("issue_number", 0)
            # Create proper Markdown link
            github_link = f"https://github.com/{repo}/issues/{number}"
            
            output.append(
                f"### [{repo} #{number}]({github_link}): {issue.get('issue_title', 'Untitled')}"
            )
            output.append("")
            output.append("**Created by:** " + issue.get("user_login", "unknown"))
            output.append(
                "**Created on:** " + format_date(issue.get("created_at", "unknown"))
            )
            
            # Add labels if present
            if "labels" in issue and issue["labels"]:
                output.append("**Labels:** " + ", ".join(issue["labels"]))
            
            output.append("")
            if "body" in issue and issue["body"]:
                # Wrap the issue body text for better readability
                output.append(wrap_text(issue["body"]))
            else:
                output.append("*No description provided*")
            output.append("\n---\n")

    # Format pull requests with GitHub links
    if prs:
        output.append("\n## New Pull Requests")
        for pr in prs:
            repo = pr.get("repository", "unknown/repo")
            number = pr.get("issue_number", 0)
            # Create proper Markdown link
            github_link = f"https://github.com/{repo}/pull/{number}"
            
            output.append(
                f"### [{repo} #{number}]({github_link}): {pr.get('issue_title', 'Untitled')}"
            )
            output.append("")
            output.append("**Created by:** " + pr.get("user_login", "unknown"))
            output.append("**Created on:** " + format_date(pr.get("created_at", "unknown")))
            
            # Add labels if present
            if "labels" in pr and pr["labels"]:
                output.append("**Labels:** " + ", ".join(pr["labels"]))
            
            output.append("")
            if "body" in pr and pr["body"]:
                # Wrap the PR body text for better readability
                output.append(wrap_text(pr["body"]))
            else:
                output.append("*No description provided*")
            output.append("\n---\n")

    # Format comments with links to parent issues/PRs
    if comments:
        output.append("\n## Recent Comments")
        for comment in comments:
            issue_type = "PR" if comment.get("is_pull_request", False) else "Issue"
            repo = comment.get("repository", "unknown/repo")
            number = comment.get("issue_number", 0)
            github_link = "https://github.com/" + repo + "/issues/" + str(number)

            output.append(
                "### Comment on ["
                + issue_type
                + " #"
                + str(number)
                + "]("
                + github_link
                + ") - "
                + comment.get("issue_title", "Untitled")
            )
            output.append("**Author:** " + comment.get("user_login", "unknown"))
            output.append("**Repository:** " + repo)
            output.append("**Created:** " + comment.get("created_at", "unknown date"))

            # Truncate very long comments
            comment_text = (
                comment.get("body", "") if comment.get("body") else "(Empty comment)"
            )
            if len(comment_text) > 500:
                comment_text = comment_text[:497] + "..."

            # Format the comment body with wrapping
            if "body" in comment and comment["body"]:
                output.append(wrap_text(comment["body"]))
            else:
                output.append("*No comment text provided*")
            output.append("\n" + "-" * 50 + "\n")

    # Add a references section with all links in one place
    output.append("\n## References")
    output.append("### Issues")
    valid_issues = [issue for issue in issues if issue.get("issue_number", 0) > 0]
    if valid_issues:
        for issue in valid_issues:
            repo = issue.get("repository", "unknown/repo")
            number = issue.get("issue_number", 0)
            title = issue.get("issue_title", "")
            if number > 0 and title:
                github_link = f"https://github.com/{repo}/issues/{number}"
                output.append(f"- [{repo} #{number}: {title}]({github_link})")
    else:
        output.append("*No issues in this time period*")

    output.append("\n### Pull Requests")
    valid_prs = [pr for pr in prs if pr.get("issue_number", 0) > 0]
    if valid_prs:
        for pr in valid_prs:
            repo = pr.get("repository", "unknown/repo")
            number = pr.get("issue_number", 0)
            title = pr.get("issue_title", "")
            if number > 0 and title:
                github_link = f"https://github.com/{repo}/pull/{number}"
                output.append(f"- [{repo} #{number}: {title}]({github_link})")
    else:
        output.append("*No pull requests in this time period*")

    return "\n".join(output)


def send_to_llm(
    report_text,
    api_key,
    model_name="claude-3-7-sonnet-latest",
    custom_prompt=None,
    dry_run=False,
    provider="anthropic",
):
    """
    Send the report to the specified LLM for summarization.

    Args:
        report_text: The text of the report to summarize
        api_key: API key for the LLM service
        model_name: The model name to use (default: "claude-3-7-sonnet-latest")
        custom_prompt: Optional custom prompt to use
        dry_run: If True, only print the prompt without making API calls
        provider: LLM provider to use (default: "anthropic", can also be "openai")

    Returns:
        The LLM response
    """
    # Check if the report needs to be chunked
    report_chunks = chunk_report_for_llm(report_text)

    if len(report_chunks) > 1:
        # If we have multiple chunks, process each one separately
        all_responses = []
        for i, chunk in enumerate(report_chunks):
            print(
                "Processing chunk " + str(i + 1) + "/" + str(len(report_chunks)) + "..."
            )

            # Default prompt for chunked reports - updated to request structured data
            prompt = (
                """
            This is chunk """
                + str(i + 1)
                + "/"
                + str(len(report_chunks))
                + """ from a GitHub activity report.
            
            Please analyze this chunk and provide a structured summary with the following sections.
            IMPORTANT: Use EXACTLY these section headers and formats to ensure statistics can be properly aggregated:
            
            ## STATS
            - Issues in this chunk: [number]
            - PRs in this chunk: [number]
            - Comments in this chunk: [number]
            - Authors in this chunk: [comma-separated list with no other text]
            - Repositories in this chunk: [comma-separated list of repositories]
            
            ## CONTRIBUTOR_DATA
            Create a table with EXACTLY these columns:
            | Contributor | PRs Created | Issues Created | Comments Made | Total Activity |
            
            Include ALL contributors with their exact counts.
            Use number values only in the table cells, not text descriptions.
            Add a "TOTAL" row at the bottom that sums each column.
            
            IMPORTANT: The "TOTAL" row should match the actual database counts exactly:
            - The sum of the "PRs Created" column MUST EQUAL {num_prs}
            - The sum of the "Issues Created" column MUST EQUAL {num_issues}
            - The sum of the "Comments Made" column MUST EQUAL {num_comments}
            - The "Total Activity" column should equal the sum of the other columns for each contributor
            
            CRITICAL: Double-check that the "Comments Made" TOTAL equals EXACTLY {num_comments}, which is the correct count from the database.
            
            ## KEY_THEMES
            - Main areas of development or focus in this chunk
            - Notable features being worked on
            - Significant bugs or issues being addressed
            
            ## DETAILS
            - Brief but substantive descriptions of the most important issues and PRs
            - Include not just what they are but WHY they matter
            - Describe the technical approach being taken
            - Discuss its significance to the project's roadmap
            - Mention any broader implications or dependencies
            - Note any related discussions or decisions
            
            IMPORTANT: Ensure ALL numerical data is accurate - use exact counts from the data.
            """
            )
            full_prompt = prompt + "\n\n" + chunk

            if dry_run:
                print("\n===== DRY RUN: PROMPT FOR CHUNK " + str(i + 1) + " =====")
                print("Model: " + model_name)
                print("Prompt length: " + str(len(full_prompt)) + " characters")
                print("\n--- Prompt start ---")
                print(
                    full_prompt[:1000] + "..."
                    if len(full_prompt) > 1000
                    else full_prompt
                )
                print("--- Prompt end ---\n")
                all_responses.append(
                    "[DRY RUN] Chunk "
                    + str(i + 1)
                    + " summary would be generated here."
                )
            else:
                try:
                    if provider == "anthropic":
                        # Create a ChatAnthropic instance
                        if not ANTHROPIC_AVAILABLE:
                            raise ImportError("ChatAnthropic is not available. Please install with: pip install chatlas")
                        chat = ChatAnthropic(api_key=api_key, model=model_name)
                    elif provider == "openai":
                        # Create a ChatOpenAI instance
                        if not OPENAI_AVAILABLE:
                            raise ImportError("ChatOpenAI is not available. Please install with: pip install chatlas")
                        chat = ChatOpenAI(api_key=api_key, model=model_name)
                    else:
                        raise ValueError("Invalid provider. Use 'anthropic' or 'openai'.")

                    # Get response
                    response = chat.chat(full_prompt, echo="none")
                    all_responses.append(str(response))
                except Exception as e:
                    all_responses.append(
                        "Error processing chunk " + str(i + 1) + ": " + str(e)
                    )

        # Combine all responses
        combined_response = "\n\n".join(all_responses)

        # Send combined summaries for final synthesis with improved prompt
        final_prompt = """
        You've been given summaries from different chunks of a GitHub activity report. 
        Each chunk contains structured sections including STATS, CONTRIBUTOR_DATA, KEY_THEMES, and DETAILS.
        
        **MOST IMPORTANT RULE: At the beginning of the input you've been given
        IMPORTANT COUNT DATA with the EXACT number of issues, PRs, and comments.
        You MUST use these EXACT numbers in your Key Metrics section. Do not
        calculate your own totals.**
        
        Your task is to synthesize these into a SINGLE COHERENT REPORT with the following sections.
        **Format your response using Markdown syntax** to make it compatible with tools like Slack:
        
        ## Executive Summary
        A comprehensive overview of the overall activity and the most significant developments.
        Be specific and detailed about what's happening in the project.
        
        ## Key Metrics
        CRITICAL: You MUST use the EXACT numbers from the "IMPORTANT COUNT DATA" section at the beginning of this report:
        - Total issues: [Insert the EXACT number from IMPORTANT COUNT DATA]
        - Total PRs: [Insert the EXACT number from IMPORTANT COUNT DATA]
        - Total comments: [Insert the EXACT number from IMPORTANT COUNT DATA]
        - Most active repositories: List the repositories from all chunks with the highest activity
        
        **Contributors:**
        Create a complete table showing ALL active contributors including bots and automated services.
        The table MUST include:
        | Contributor | PRs Created | Issues Created | Comments Made | Total Activity |
        
        Add a "TOTAL" row at the bottom that sums each column.
        
        IMPORTANT: The "TOTAL" row should match the actual database counts exactly:
        - The sum of the "PRs Created" column MUST EQUAL {num_prs}
        - The sum of the "Issues Created" column MUST EQUAL {num_issues}
        - The sum of the "Comments Made" column MUST EQUAL {num_comments}
        - The "Total Activity" column should equal the sum of the other columns for each contributor
        
        CRITICAL: Double-check that the "Comments Made" TOTAL equals EXACTLY {num_comments}, which is the correct count from the database.
        
        ## Development Focus Areas
        Identify 3-5 main areas of development based on the data, such as:
        - New features being developed
        - Major bug fixes or issues being addressed
        - Infrastructure or technical improvements
        - Documentation or community initiatives
        
        For each focus area, provide detailed context on why this work matters to the project.
        
        ## Highlights
        Detailed descriptions of the most important issues and PRs, organized by focus area.
        Include relevant issue/PR numbers for reference.
        
        For each highlight:
        - Explain what problem it solves
        - Describe the technical approach
        - Note its significance to the project
        - Mention any related discussions or decisions
        
        ## Action Items
        Suggest 3-5 areas that may need attention based on the activity, explain why each needs attention,
        and what the potential impact could be.
        
        IMPORTANT: 
        - Your report should be a single coherent document that doesn't reference individual chunks
        - All numerical data MUST be accurate - the total counts must exactly match the sum of the individual chunks
        - Exclude any references to bots like github-actions[bot] in your analysis
        - Use rich Markdown formatting including headers, lists, tables, and emphasis for readability
        """

        full_final_prompt = final_prompt + "\n\n" + combined_response

        if dry_run:
            print("\n===== DRY RUN: FINAL SYNTHESIS PROMPT =====")
            print("Model: " + model_name)
            print("Prompt length: " + str(len(full_final_prompt)) + " characters")
            print("\n--- Prompt start ---")
            print(
                full_final_prompt[:1000] + "..."
                if len(full_final_prompt) > 1000
                else full_final_prompt
            )
            print("--- Prompt end ---\n")
            return "[DRY RUN] This is where the final synthesis would be shown."
        else:
            try:
                if provider == "anthropic":
                    # Create a ChatAnthropic instance
                    if not ANTHROPIC_AVAILABLE:
                        raise ImportError("ChatAnthropic is not available. Please install with: pip install chatlas")
                    chat = ChatAnthropic(api_key=api_key, model=model_name)
                elif provider == "openai":
                    # Create a ChatOpenAI instance
                    if not OPENAI_AVAILABLE:
                        raise ImportError("ChatOpenAI is not available. Please install with: pip install chatlas")
                    chat = ChatOpenAI(api_key=api_key, model=model_name)
                else:
                    raise ValueError("Invalid provider. Use 'anthropic' or 'openai'.")

                # Get final synthesis response - return only this, not the individual chunks
                final_response = chat.chat(full_final_prompt, echo="none")
                return str(final_response)
            except Exception as e:
                return (
                    "Error creating final synthesis: "
                    + str(e)
                    + "\n\nRaw chunk data (for debugging):\n"
                    + combined_response
                )
    else:
        # For single chunk reports - updated prompt to match the structure of the final report
        prompt = """
        This is a GitHub activity report with recent issues, pull requests, and comments.
        
        Please provide a concise summary with the following sections.
        
        ## Executive Summary
        A comprehensive overview of the overall activity and the most significant developments.
        Include the following:
        - The overall state of the project and its momentum
        - Major themes or patterns across the reported activity
        - Implications of these developments for users and developers
        - Notable shifts in project direction or focus
        
        ## Key Metrics
        - Total issues: {num_issues}
        - Total PRs: {num_prs}
        - Total comments: {num_comments}
        - List all repositories mentioned in the report
        
        **Contributors:**
        Create a complete table showing ALL active contributors including bots and automated services.
        The table MUST include:
        | Contributor | PRs Created | Issues Created | Comments Made | Total Activity |
        
        Add a "TOTAL" row at the bottom that sums each column.
        
        IMPORTANT: The "TOTAL" row should match the actual database counts exactly:
        - The sum of the "PRs Created" column MUST EQUAL {num_prs}
        - The sum of the "Issues Created" column MUST EQUAL {num_issues}
        - The sum of the "Comments Made" column MUST EQUAL {num_comments}
        - The "Total Activity" column should equal the sum of the other columns for each contributor
        
        CRITICAL: Double-check that the "Comments Made" TOTAL equals EXACTLY {num_comments}, which is the correct count from the database.
        
        ## Development Focus Areas
        Identify 3-5 main areas of development based on the data, such as:
        - New features being developed
        - Major bug fixes or issues being addressed
        - Infrastructure or technical improvements
        - Documentation or community initiatives
        
        For each focus area:
        - Explain why this work matters to the project
        - Describe the potential impact on users and developers
        - Note any dependencies or connections between focus areas
        - Identify any patterns or trends in this development area
        
        ## Highlights
        Detailed descriptions of the most important issues and PRs, organized by focus area.
        
        For each highlight:
        - Use proper Markdown syntax to create links to GitHub issues/PRs like this: [#1234](https://github.com/owner/repo/issues/1234)
        - Explain what problem it solves and why it matters
        - Describe the technical approach being taken
        - Discuss its significance to the project's roadmap
        - Mention any broader implications or dependencies
        - Note any related discussions or decisions
        
        IMPORTANT: Always use full Markdown links for any issues or PRs mentioned.
        
        ## Action Items
        Suggest 3-5 areas that may need attention based on the activity.
        For each action item:
        - Explain why each needs attention
        - Describe the potential impact if addressed or not addressed
        - Note any dependencies or prerequisites
        - Suggest possible approaches or next steps
        """.format(
            num_issues=len(report_text.get("issues", [])),
            num_prs=len(report_text.get("pull_requests", [])),
            num_comments=len(report_text.get("comments", [])),
        )

        full_prompt = prompt + "\n\n" + report_text

        if dry_run:
            print("\n===== DRY RUN: PROMPT =====")
            print("Model: " + model_name)
            print("Prompt length: " + str(len(full_prompt)) + " characters")
            print("\n--- Prompt start ---")
            print(
                full_prompt[:1000] + "..." if len(full_prompt) > 1000 else full_prompt
            )
            print("--- Prompt end ---\n")
            return "[DRY RUN] This is where the LLM response would be shown."
        else:
            try:
                if provider == "anthropic":
                    # Create a ChatAnthropic instance
                    if not ANTHROPIC_AVAILABLE:
                        raise ImportError("ChatAnthropic is not available. Please install with: pip install chatlas")
                    chat = ChatAnthropic(api_key=api_key, model=model_name)
                elif provider == "openai":
                    # Create a ChatOpenAI instance
                    if not OPENAI_AVAILABLE:
                        raise ImportError("ChatOpenAI is not available. Please install with: pip install chatlas")
                    chat = ChatOpenAI(api_key=api_key, model=model_name)
                else:
                    raise ValueError("Invalid provider. Use 'anthropic' or 'openai'.")

                # Get response
                response = chat.chat(full_prompt, echo="none")
                return str(response)
            except Exception as e:
                return "Error: " + str(e)


@click.group()
def cli():
    """GitHub Issues Repo Database (GIRD) Activity Report Generator."""
    pass


@cli.command()
@click.option(
    "--db-path",
    default=DEFAULT_DB_PATH,
    help=f"Path to GIRD SQLite database (default: {DEFAULT_DB_PATH})",
)
@click.option(
    "--output",
    default=None,
    help="Path to save the report (default: print to stdout)",
)
@click.option(
    "--days",
    default=7,
    help="Number of days to include in the report (default: 7)",
)
@click.option(
    "--repositories",
    default=None,
    help="Comma-separated list of repositories to include (default: all)",
)
@click.option(
    "--llm-api-key",
    default=None,
    help="API key for the LLM (default: LLM_API_KEY environment variable)",
)
@click.option(
    "--llm-model",
    default="claude-3-7-sonnet-latest",
    help="Model name for the LLM (default: claude-3-7-sonnet-latest)",
)
@click.option(
    "--llm-provider",
    default="anthropic",
    type=click.Choice(["anthropic", "openai"]),
    help="LLM provider to use (default: anthropic)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Don't actually send to LLM, just show what would be sent",
)
@click.option(
    "--custom-prompt",
    default=None,
    help="Custom prompt to use for the LLM (overrides the default)",
)
def cli(
    db_path,
    output,
    days,
    repositories,
    llm_api_key,
    llm_model,
    llm_provider,
    dry_run,
    custom_prompt,
):
    """Generate a report of GitHub activity from a GIRD database."""
    # Get API key from environment if not provided
    if llm_api_key is None:
        llm_api_key = os.environ.get("LLM_API_KEY")
        if llm_api_key is None and not dry_run:
            raise ValueError(
                "LLM API key must be provided via --llm-api-key or LLM_API_KEY environment variable"
            )
    
    # Check provider availability
    if not dry_run:
        if llm_provider == "anthropic" and not ANTHROPIC_AVAILABLE:
            raise ImportError("ChatAnthropic is not available. Please install with: pip install chatlas")
        elif llm_provider == "openai" and not OPENAI_AVAILABLE:
            raise ImportError("ChatOpenAI is not available. Please install with: pip install chatlas")
    
    # Open database connection
    with GirdDatabase(db_path) as gird_db:
        # Determine date range
        end_date_obj = datetime.datetime.now()
        start_date_obj = end_date_obj - datetime.timedelta(days=days)

        # Get activity data
        activity = gird_db.get_recent_activity(
            start_date_obj, end_date_obj, repositories.split(",") if repositories else None
        )

        # Format for output
        report = format_activity_for_report(activity, start_date=start_date_obj, end_date=end_date_obj)

        # Wrap report text to fit within MAX_LINE_WIDTH
        wrapped_report = wrap_text(report)

        # Output the report
        if output:
            with open(output, "w") as f:
                f.write(wrapped_report)
            print(f"Report written to {output}")
        else:
            print(wrapped_report)

        # Send to LLM if requested
        if llm_api_key and not dry_run:
            # Send to LLM and print response
            print(f"\nSending report to {llm_model} for analysis...")
            llm_response = send_to_llm(
                wrapped_report,
                llm_api_key,
                llm_model,
                custom_prompt,
                dry_run,
                provider=llm_provider,
            )
            print(f"\n--- {llm_model} Summary ---\n")
            print(llm_response)


if __name__ == "__main__":
    cli()
