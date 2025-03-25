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

    lines = text.split("\n")
    wrapped_lines = []

    for line in lines:
        # Skip wrapping for code blocks, tables, and other special Markdown elements
        if (
            line.startswith("```")
            or line.startswith("|")
            or line.startswith("#")
            or line.startswith("- ")
            or line.startswith("* ")
            or line.startswith("> ")
            or line.strip() == "---"
            or line.strip() == ""
        ):
            wrapped_lines.append(line)
            continue

        # Wrap the line
        current_width = 0
        wrapped_line = []
        words = line.split(" ")

        for word in words:
            if current_width + len(word) + 1 > width and current_width > 0:
                wrapped_lines.append(" ".join(wrapped_line))
                wrapped_line = [word]
                current_width = len(word)
            else:
                wrapped_line.append(word)
                current_width += len(word) + 1

        if wrapped_line:
            wrapped_lines.append(" ".join(wrapped_line))

    return "\n".join(wrapped_lines)


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
        date_obj = datetime.datetime.fromisoformat(date_str.replace("Z", "+00:00"))
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
            Dictionary with keys 'issues', 'pull_requests', 'comments', and 'contributors', each containing
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

        # Get all contributors within the date range
        all_contributors = self.get_top_contributors(
            start_date, end_date, repos, limit=None
        )

        # Separate issues and pull requests
        issues = [issue for issue in all_issues if not issue["is_pull_request"]]
        pull_requests = [pr for pr in all_issues if pr["is_pull_request"]]

        return {
            "issues": issues,
            "pull_requests": pull_requests,
            "comments": all_comments,
            "contributors": all_contributors,
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
        limit: int = None,
    ) -> List[Dict]:
        """Get top contributors based on activity within the date range.

        Args:
            start_date: Start date for the activity window
            end_date: End date for the activity window
            repos: Optional list of repository names to filter by
            limit: Maximum number of contributors to return (None for all contributors)

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
        GROUP BY 
            user_id, user_login, user_type
        ORDER BY 
            total_activity DESC
        """
        )

        # Only add LIMIT clause if limit is specified
        if limit is not None:
            query += " LIMIT ?"
            params = (
                [start_date_str, end_date_str]
                + repo_params
                + [start_date_str, end_date_str]
                + repo_params
                + [limit]
            )
        else:
            params = (
                [start_date_str, end_date_str]
                + repo_params
                + [start_date_str, end_date_str]
                + repo_params
            )

        cursor.execute(query, params)

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
    # Strip markdown comments before chunking
    report = strip_markdown_comments(report)

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


def strip_markdown_comments(text):
    """
    Remove GitHub-style markdown comments from the text to reduce size for LLM processing.

    Args:
        text (str): The markdown text that may contain HTML-style comments

    Returns:
        str: Text with all <!-- --> comments removed
    """
    # Pattern to match HTML-style comments (including multiline)
    pattern = r"<!--(.*?)-->"

    # Remove all comments using re.DOTALL to match across multiple lines
    cleaned_text = re.sub(pattern, "", text, flags=re.DOTALL)

    # Remove any empty lines that might be left
    cleaned_text = re.sub(r"\n\s*\n", "\n\n", cleaned_text)

    return cleaned_text


def format_activity_for_report(
    activity,
    start_date=None,
    end_date=None,
    verbose=False,
    dry_run=False,
):
    """
    Format the activity data for LLM consumption.

    Args:
        activity: Activity dictionary with issues, prs and comments
        start_date: Start date of the report period
        end_date: End date of the report period
        verbose: Whether to include full details like comment bodies
        dry_run: If True, show full content regardless of verbose flag

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

    # Add contributors table
    contributors = activity.get("contributors", [])
    if contributors:
        output.append("\n## Contributors")
        output.append(
            "| Contributor | Issues Created | PRs Created | Comments Made | Total Activity |"
        )
        output.append(
            "|------------|----------------|-------------|---------------|----------------|"
        )

        # Sort contributors by total activity (descending)
        sorted_contributors = sorted(
            contributors, key=lambda x: x.get("total_activity", 0), reverse=True
        )

        # Display ALL contributors, not just the top ones
        for contributor in sorted_contributors:
            login = contributor.get("user_login", "unknown")
            issues_count = contributor.get("issue_count", 0)
            prs_count = contributor.get("pr_count", 0)
            comments_count = contributor.get("comment_count", 0)
            total_activity = contributor.get("total_activity", 0)

            output.append(
                f"| {login} | {issues_count} | {prs_count} | {comments_count} | {total_activity} |"
            )

        # Add totals row
        total_issues = sum(c.get("issue_count", 0) for c in contributors)
        total_prs = sum(c.get("pr_count", 0) for c in contributors)
        total_comments = sum(c.get("comment_count", 0) for c in contributors)
        total_activity = sum(c.get("total_activity", 0) for c in contributors)

        output.append(
            f"| **TOTAL** | **{total_issues}** | **{total_prs}** | **{total_comments}** | **{total_activity}** |"
        )

        # Add explanation if totals don't match
        if (
            total_issues != len(issues)
            or total_prs != len(prs)
            or total_comments != len(comments)
        ):
            output.append(
                "\n**Note:** Totals may differ from summary counts due to filters or data processing."
            )

    # Format issues with GitHub links
    if issues and (verbose or dry_run):
        # Only show issue details when verbose flag is enabled
        # Filter out invalid entries
        valid_issues = [
            issue
            for issue in issues
            if issue.get("number", 0) > 0 and issue.get("title", "").strip()
        ]

        if valid_issues:
            output.append("\n## New Issues")
            for issue in valid_issues:
                repo = issue.get("repository", "unknown/repo")
                number = issue.get("number", 0)
                title = issue.get("title", "").strip()

                # More concise issue reference format for the report
                output.append(f"### {repo}#{number}: {title}")
                output.append("**Created by:** " + issue.get("user_login", "unknown"))
                output.append(
                    "**Created on:** " + format_date(issue.get("created_at", "unknown"))
                )

                # Add labels if present
                if "labels" in issue and issue["labels"]:
                    output.append("**Labels:** " + ", ".join(issue["labels"]))

                output.append("")
                issue_body = issue.get("body", "")
                if issue_body:
                    # Strip markdown comments from the issue body
                    issue_body = strip_markdown_comments(issue_body)
                    output.append(wrap_text(issue_body))
                else:
                    output.append("*No description provided*")
                output.append("\n---\n")
    elif issues and not verbose and not dry_run:
        # Add a note about issues when not in verbose mode
        valid_issues = [
            issue
            for issue in issues
            if issue.get("number", 0) > 0 and issue.get("title", "").strip()
        ]
        if valid_issues:
            output.append("\n## New Issues")
            output.append(
                f"*{len(valid_issues)} issues found. Use --verbose to see details.*\n"
            )

    # Format pull requests with GitHub links
    if prs and (verbose or dry_run):
        # Only show PR details when verbose flag is enabled
        # Filter out invalid entries
        valid_prs = [
            pr for pr in prs if pr.get("number", 0) > 0 and pr.get("title", "").strip()
        ]

        if valid_prs:
            output.append("\n## New Pull Requests")
            for pr in valid_prs:
                repo = pr.get("repository", "unknown/repo")
                number = pr.get("number", 0)
                title = pr.get("title", "").strip()

                # More concise PR reference format for the report
                output.append(f"### {repo}#{number}: {title}")
                output.append("**Created by:** " + pr.get("user_login", "unknown"))
                output.append(
                    "**Created on:** " + format_date(pr.get("created_at", "unknown"))
                )

                # Add labels if present
                if "labels" in pr and pr["labels"]:
                    output.append("**Labels:** " + ", ".join(pr["labels"]))

                output.append("")
                pr_body = pr.get("body", "")
                if pr_body:
                    # Strip markdown comments from the PR body
                    pr_body = strip_markdown_comments(pr_body)
                    output.append(wrap_text(pr_body))
                else:
                    output.append("*No description provided*")
                output.append("\n---\n")
    elif prs and not verbose and not dry_run:
        # Add a note about PRs when not in verbose mode
        valid_prs = [
            pr for pr in prs if pr.get("number", 0) > 0 and pr.get("title", "").strip()
        ]
        if valid_prs:
            output.append("\n## New Pull Requests")
            output.append(
                f"*{len(valid_prs)} pull requests found. Use --verbose to see details.*\n"
            )

    # Format comments with links to parent issues/PRs
    if comments and (verbose or dry_run):
        # Only show comments section when verbose flag is enabled
        # Filter out invalid entries
        valid_comments = [
            comment
            for comment in comments
            if comment.get("issue_number", 0) > 0
            and (
                comment.get("issue_title", "").strip()
                or comment.get("body", "").strip()
            )
        ]

        if valid_comments:
            output.append("\n## Recent Comments")
            for comment in valid_comments:
                repo = comment.get("repository", "unknown/repo")
                number = comment.get("issue_number", 0)
                is_pr = comment.get("is_pull_request", False)
                title = comment.get("issue_title", "").strip() or "Untitled"

                # More concise comment reference format for the report
                comment_type = "PR" if is_pr else "Issue"
                output.append(
                    f"### Comment on {repo}#{number} ({comment_type}): {title}"
                )
                output.append("**Author:** " + comment.get("user_login", "unknown"))
                output.append("**Repository:** " + repo)
                output.append(
                    "**Created:** " + comment.get("created_at", "unknown date")
                )

                # Get comment body and strip markdown comments
                comment_body = comment.get("body", "")
                if comment_body:
                    # Strip markdown comments from the comment body
                    comment_body = strip_markdown_comments(comment_body)

                # Truncate very long comments
                comment_text = comment_body if comment_body else "(Empty comment)"
                if len(comment_text) > 500:
                    comment_text = comment_text[:497] + "..."

                # Format the comment body with wrapping
                output.append(wrap_text(comment_text))
                output.append("\n" + "-" * 50 + "\n")
    elif comments and not verbose and not dry_run:
        # Add a note about comments when not in verbose mode
        output.append("\n## Recent Comments")
        output.append(
            f"*{len(comments)} comments found. Use --verbose to see comment details.*\n"
        )

    # Add a references section with all links in one place if in verbose mode
    if verbose or dry_run:
        output.append("\n## References")
        output.append("### Issues")
        # Filter valid issues for the References section too
        valid_issues = [
            issue
            for issue in issues
            if issue.get("number", 0) > 0 and issue.get("title", "").strip()
        ]
        valid_issues.sort(
            key=lambda x: x.get("repository", "") + str(x.get("number", 0))
        )

        for issue in valid_issues:
            if not issue.get("is_pull_request", False):
                repo = issue.get("repository", "unknown/repo")
                number = issue.get("number", 0)
                title = issue.get("title", "").strip()
                # Skip entries with no title or issue number 0
                if number > 0 and title:
                    # Format as clickable markdown links
                    github_link = f"https://github.com/{repo}/issues/{number}"
                    output.append(f"- [{repo}#{number}: {title}]({github_link})")

        output.append("\n### Pull Requests")
        # Filter valid PRs for the References section too
        valid_prs = [
            pr for pr in prs if pr.get("number", 0) > 0 and pr.get("title", "").strip()
        ]
        valid_prs.sort(key=lambda x: x.get("repository", "") + str(x.get("number", 0)))

        for pr in valid_prs:
            repo = pr.get("repository", "unknown/repo")
            number = pr.get("number", 0)
            title = pr.get("title", "").strip()
            # Skip entries with no title or PR number 0
            if number > 0 and title:
                # Format as clickable markdown links
                github_link = f"https://github.com/{repo}/pull/{number}"
                output.append(f"- [{repo}#{number}: {title}]({github_link})")
    return "\n".join(output)


def send_to_llm(
    report_text,
    api_key,
    model_name="claude-3-7-sonnet-latest",
    custom_prompt=None,
    dry_run=False,
    provider="anthropic",
    activity=None,
    verbose=False,
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
        activity: The original activity data, used to create a verbose report for the LLM
        verbose: Whether verbose mode is enabled in the user output

    Returns:
        The LLM response
    """
    # If activity data is provided and the report is not already verbose,
    # create a verbose version specifically for the LLM
    if activity and not verbose and not dry_run:
        print("Creating detailed report for LLM analysis...")
        # Generate a verbose version of the report with all issue/PR/comment details
        llm_report_text = format_activity_for_report(
            activity, verbose=True, dry_run=True
        )
        # Use this verbose report for LLM processing
        report_text = llm_report_text

    # Strip markdown comments before chunking
    report_text = strip_markdown_comments(report_text)

    # Check if the report needs to be chunked
    report_chunks = chunk_report_for_llm(report_text)

    if len(report_chunks) > 1:
        print(f"Report split into {len(report_chunks)} chunks")

        # If we have multiple chunks, process each one separately
        all_responses = []
        for i, chunk in enumerate(report_chunks):
            print(
                "Processing chunk " + str(i + 1) + "/" + str(len(report_chunks)) + "..."
            )

            # Print chunk size info for debugging
            print(f"  Chunk {i + 1} size: {len(chunk)} characters")
            if dry_run:
                print(f"  Chunk {i + 1} preview (first 100 chars): {chunk[:100]}...")

            # Default prompt for chunked reports - updated to request structured data
            prompt = f"""
            This is chunk {i + 1}/{len(report_chunks)} from a GitHub activity report.
            
            Please analyze this chunk and provide a structured summary with the following sections.
            ABSOLUTELY CRITICAL: ONLY use data that is explicitly stated in the report chunk provided. 
            DO NOT make up or estimate ANY statistics or information not directly mentioned in the chunk.
            NEVER invent contributors, commit counts, PR counts, issue counts, or other metrics.
            If certain data is not present in the chunk, simply state "Data not available in this chunk" for that section.
            
            IMPORTANT: Use EXACTLY these section headers and formats to ensure statistics can be properly aggregated:
            
            ## STATISTICS
            - Number of new issues: [ONLY if explicitly counted in chunk, otherwise "Data not available"]
            - Number of new PRs: [ONLY if explicitly counted in chunk, otherwise "Data not available"]
            - Number of comments: [ONLY if explicitly counted in chunk, otherwise "Data not available"]
            - Most active repositories: [ONLY repositories explicitly mentioned in chunk]
            
            ## KEY DEVELOPMENTS
            - List ONLY specific issues, PRs, or comments actually mentioned in this chunk
            - Do not generalize or make claims about "focus areas" unless explicitly stated
            - If no clear developments are present, state "No specific key developments identified in this chunk"
            
            ## DETAILS
            - ONLY describe issues, PRs, or comments specifically mentioned in this chunk
            - Use only facts presented, do not add interpretation unless it's clearly stated in the text
            - If minimal details are present, it's fine to say "Limited details available in this chunk"
            
            FINAL REMINDER: You MUST strictly adhere to facts presented in the chunk. Fabricating data is strictly prohibited.
            """
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
                            raise ImportError(
                                "ChatAnthropic is not available. Please install with: pip install chatlas"
                            )
                        chat = ChatAnthropic(api_key=api_key, model=model_name)
                    elif provider == "openai":
                        # Create a ChatOpenAI instance
                        if not OPENAI_AVAILABLE:
                            raise ImportError(
                                "ChatOpenAI is not available. Please install with: pip install chatlas"
                            )
                        chat = ChatOpenAI(api_key=api_key, model=model_name)
                    else:
                        raise ValueError(
                            "Invalid provider. Use 'anthropic' or 'openai'."
                        )

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
        Each chunk contains structured sections including contributor data, statistics, key developments, and details.
        
        **MOST IMPORTANT RULE: You MUST preserve and include the COMPLETE CONTRIBUTOR TABLE exactly as it appears.
        IT IS MANDATORY TO INCLUDE THE FULL TABLE - NO EXCEPTIONS.**
        
        Your task is to synthesize these into a SINGLE COHERENT REPORT with the following sections.
        **Format your response using Markdown syntax** to make it compatible with tools like Slack:
        
        ## Executive Summary
        A comprehensive overview of the overall activity and the most significant developments.
        Be specific and detailed about what's happening in the project.
        
        ## Key Metrics
        - Total issues: [Copy exact number from the input]
        - Total PRs: [Copy exact number from the input]
        - Total comments: [Copy exact number from the input]
        - Most active repositories: List the repositories from all chunks with the highest activity
        
        ## Contributors
        **YOU MUST REPRODUCE THE ENTIRE CONTRIBUTOR TABLE FROM THE REPORT**
        **IT IS ESSENTIAL THAT YOU INCLUDE THE FULL TABLE IN MARKDOWN FORMAT**
        **DO NOT ABBREVIATE, SUMMARIZE OR DROP THIS TABLE**
        **INCLUDE EVERY SINGLE CONTRIBUTOR AND THEIR STATISTICS**
        **MAINTAIN the exact same format, columns, and sorting as in the original report**
        **INCLUDE the TOTAL row at the bottom of the table**
        
        ## Significant Developments
        IMPORTANT: This is the most valuable section of your analysis. DEEPLY ANALYZE all the content you've
        been given about issues, pull requests, and comments to provide a comprehensive overview of:
        
        - Major features being developed or completed
        - Significant bugs fixed or issues addressed
        - Important architectural changes or decisions
        - Recurring themes or focus areas in the development work
        
        Include specific examples with references to issues/PRs as clickable markdown links (e.g., [repo#123](https://github.com/repo/issues/123))
        Explain the importance and implications of the key developments:
        - What problems are these changes solving?
        - What do these changes mean for the project's future direction?
        - How do these changes connect to the project's overall goals?
        - What would someone who hasn't been following the project need to know?
        
        Organize this information in a way that helps the reader understand the overall direction and 
        priorities of the project, rather than just listing individual changes.
        
        IMPORTANT: 
        - Your report should be a single coherent document that doesn't reference individual chunks
        - All numerical data MUST be accurate based on the data provided in the input
        - Use rich Markdown formatting including headers, lists, tables, and emphasis for readability
        - Focus on DETAILED ANALYSIS of the actual content of issues, PRs and comments
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
                        raise ImportError(
                            "ChatAnthropic is not available. Please install with: pip install chatlas"
                        )
                    chat = ChatAnthropic(api_key=api_key, model=model_name)
                elif provider == "openai":
                    # Create a ChatOpenAI instance
                    if not OPENAI_AVAILABLE:
                        raise ImportError(
                            "ChatOpenAI is not available. Please install with: pip install chatlas"
                        )
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
        Please analyze this GitHub activity report and provide a structured summary.
        
        ABSOLUTELY CRITICAL: ONLY use data that is explicitly stated in the report provided. 
        DO NOT make up or estimate ANY statistics or information not directly mentioned.
        NEVER invent contributors, commit counts, PR counts, issue counts, or other metrics.
        
        Your summary should include:
        
        1. Executive Summary - Overall activity and key themes
           - Only mention trends or focus areas if they are explicitly evident in the report
           - If certain information is not clear from the report, say so rather than making assumptions
        
        2. Key Metrics - Use EXACT counts from the report
           - Total issues: [exact count ONLY if provided]
           - Total PRs: [exact count ONLY if provided]
           - Total comments: [exact count ONLY if provided]
           - Most active repositories: [ONLY list repositories mentioned in the report]
        
        3. Contributors - YOU MUST REPRODUCE THE ENTIRE CONTRIBUTOR TABLE FROM THE REPORT
           - IT IS ESSENTIAL THAT YOU INCLUDE THE FULL TABLE IN MARKDOWN FORMAT
           - DO NOT ABBREVIATE, SUMMARIZE OR DROP THIS TABLE 
           - INCLUDE EVERY SINGLE CONTRIBUTOR AND THEIR STATISTICS
           - MAINTAIN the exact same format, columns, and sorting as in the original report
           - INCLUDE the TOTAL row at the bottom of the table
        
        4. Significant Developments - IMPORTANT: Read ALL issue/PR descriptions and comments thoroughly
           - Identify major features being developed or completed
           - Highlight significant bugs fixed or issues addressed
           - Note any important architectural changes or decisions
           - Mention any recurring themes or focus areas in the development work
           - Provide specific examples with references to issues/PRs as clickable markdown links (e.g., [repo#123](https://github.com/repo/issues/123))
           - Explain the importance and implications of these developments
           - What do these changes mean for the project's future direction?
           - What problems are these changes solving?
           - What would someone who hasn't been following the project need to know?
        
        FINAL REMINDER: You MUST strictly adhere to facts presented in the report. Fabricating data is strictly prohibited.
        Focus on DETAILED ANALYSIS of the actual content of issues, PRs and comments to provide insight into what's
        happening in the project beyond just the numbers.
        """
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
                        raise ImportError(
                            "ChatAnthropic is not available. Please install with: pip install chatlas"
                        )
                    chat = ChatAnthropic(api_key=api_key, model=model_name)
                elif provider == "openai":
                    # Create a ChatOpenAI instance
                    if not OPENAI_AVAILABLE:
                        raise ImportError(
                            "ChatOpenAI is not available. Please install with: pip install chatlas"
                        )
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
@click.option(
    "--verbose",
    is_flag=True,
    help="Include additional details like comment bodies in the report",
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
    verbose,
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
            raise ImportError(
                "ChatAnthropic is not available. Please install with: pip install chatlas"
            )
        elif llm_provider == "openai" and not OPENAI_AVAILABLE:
            raise ImportError(
                "ChatOpenAI is not available. Please install with: pip install chatlas"
            )

    # Open database connection
    with GirdDatabase(db_path) as gird_db:
        # Determine date range
        end_date_obj = datetime.datetime.now()
        start_date_obj = end_date_obj - datetime.timedelta(days=days)

        # Get activity data
        activity = gird_db.get_recent_activity(
            start_date_obj,
            end_date_obj,
            repositories.split(",") if repositories else None,
        )

        # Format for output
        report = format_activity_for_report(
            activity,
            start_date=start_date_obj,
            end_date=end_date_obj,
            verbose=verbose,
            dry_run=dry_run,
        )

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
                activity=activity,
                verbose=verbose,
            )
            print(f"\n--- {llm_model} Summary ---\n")
            print(llm_response)


if __name__ == "__main__":
    cli()
