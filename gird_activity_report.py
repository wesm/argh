#!/usr/bin/env python3

"""
GitHub Activity Report Generator for GIRD
Generates reports for recent GitHub activity from a GIRD database.
"""

import argparse
import datetime
import json
import os
import re
import sqlite3
from typing import Dict, List, Optional, Tuple, Union

# Constants
DEFAULT_DB_PATH = "github_issues.db"
DEFAULT_DAYS = 7


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
            repo_filter = f"AND repositories.full_name IN ({repo_placeholders})"
            repo_params = repos

        # Format dates for SQLite
        start_date_str = start_date.strftime("%Y-%m-%d %H:%M:%S")
        end_date_str = end_date.strftime("%Y-%m-%d %H:%M:%S")

        # Query for contributors with counts of issues, PRs, and comments
        query = f"""
        WITH issue_counts AS (
            SELECT 
                users.id as user_id,
                users.login as user_login,
                COUNT(CASE WHEN issues.is_pull_request = 0 THEN 1 ELSE NULL END) as issue_count,
                COUNT(CASE WHEN issues.is_pull_request = 1 THEN 1 ELSE NULL END) as pr_count
            FROM 
                issues
            JOIN 
                repositories ON issues.repository_id = repositories.id
            JOIN 
                users ON issues.user_id = users.id
            WHERE 
                issues.created_at BETWEEN ? AND ?
                {repo_filter}
            GROUP BY 
                users.id
        ),
        comment_counts AS (
            SELECT 
                users.id as user_id,
                users.login as user_login,
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
                comments.created_at BETWEEN ? AND ?
                {repo_filter}
            GROUP BY 
                users.id
        )
        SELECT 
            COALESCE(i.user_id, c.user_id) as user_id,
            COALESCE(i.user_login, c.user_login) as user_login,
            COALESCE(i.issue_count, 0) as issue_count,
            COALESCE(i.pr_count, 0) as pr_count,
            COALESCE(c.comment_count, 0) as comment_count,
            (COALESCE(i.issue_count, 0) + COALESCE(i.pr_count, 0) + COALESCE(c.comment_count, 0)) as total_activity
        FROM 
            issue_counts i
        FULL OUTER JOIN 
            comment_counts c ON i.user_id = c.user_id
        ORDER BY 
            total_activity DESC
        LIMIT ?
        """

        # SQLite doesn't support FULL OUTER JOIN, so we need to use LEFT JOIN + UNION
        query = f"""
        -- Contributors from issues
        WITH issue_creators AS (
            SELECT 
                users.id as user_id,
                users.login as user_login,
                COUNT(CASE WHEN issues.is_pull_request = 0 THEN 1 ELSE NULL END) as issue_count,
                COUNT(CASE WHEN issues.is_pull_request = 1 THEN 1 ELSE NULL END) as pr_count,
                0 as comment_count
            FROM 
                issues
            JOIN 
                repositories ON issues.repository_id = repositories.id
            JOIN 
                users ON issues.user_id = users.id
            WHERE 
                issues.created_at BETWEEN ? AND ?
                {repo_filter}
            GROUP BY 
                users.id
        ),
        -- Contributors from comments
        commenters AS (
            SELECT 
                users.id as user_id,
                users.login as user_login,
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
                comments.created_at BETWEEN ? AND ?
                {repo_filter}
            GROUP BY 
                users.id
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
            SUM(issue_count) as issue_count,
            SUM(pr_count) as pr_count,
            SUM(comment_count) as comment_count,
            SUM(issue_count + pr_count + comment_count) as total_activity
        FROM 
            all_contributors
        GROUP BY 
            user_id, user_login
        ORDER BY 
            total_activity DESC
        LIMIT ?
        """

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
            repo_placeholders = ",".join("?" for _ in repos)
            repo_filter = f"AND repositories.full_name IN ({repo_placeholders})"
            repo_params = repos

        # Format dates for SQLite
        start_date_str = start_date.strftime("%Y-%m-%d")
        end_date_str = end_date.strftime("%Y-%m-%d")

        # Query for issues with most comments in the time period
        query = f"""
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
            {repo_filter}
        GROUP BY 
            i.id
        ORDER BY 
            comment_count DESC, i.updated_at DESC
        LIMIT ?
        """

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
            activity (dict): Activity data dictionary with issues, prs, and comments
            days_per_chunk (int): Number of days for each chunk

        Returns:
            list: List of dictionaries with start_date, end_date, and data for each chunk
        """
        if not activity or not (
            activity.get("issues") or activity.get("prs") or activity.get("comments")
        ):
            return []

        # Find the overall date range from the activity data
        all_dates = []

        for issue in activity.get("issues", []):
            all_dates.append(
                datetime.datetime.strptime(issue["created_at"], "%Y-%m-%dT%H:%M:%SZ")
            )

        for pr in activity.get("prs", []):
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
            chunk_data = {"issues": [], "prs": [], "comments": []}

            for issue in activity.get("issues", []):
                issue_date = datetime.datetime.strptime(
                    issue["created_at"], "%Y-%m-%dT%H:%M:%SZ"
                )
                if chunk_start <= issue_date <= chunk_end:
                    chunk_data["issues"].append(issue)

            for pr in activity.get("prs", []):
                pr_date = datetime.datetime.strptime(
                    pr["created_at"], "%Y-%m-%dT%H:%M:%SZ"
                )
                if chunk_start <= pr_date <= chunk_end:
                    chunk_data["prs"].append(pr)

            for comment in activity.get("comments", []):
                comment_date = datetime.datetime.strptime(
                    comment["created_at"], "%Y-%m-%dT%H:%M:%SZ"
                )
                if chunk_start <= comment_date <= chunk_end:
                    chunk_data["comments"].append(comment)

            # Only add chunk if it has any activity
            if chunk_data["issues"] or chunk_data["prs"] or chunk_data["comments"]:
                chunks.append(
                    {
                        "start_date": chunk_start,
                        "end_date": chunk_end,
                        "data": chunk_data,
                    }
                )

        return chunks


def chunk_report_for_claude(report, max_chars=20000):
    """
    Split a large report into smaller chunks for Claude, trying to maintain section integrity.

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


def format_activity_for_claude(
    activity, top_contributors=None, hot_issues=None, start_date=None, end_date=None
):
    """
    Format the activity data for Claude AI consumption.

    Args:
        activity: Activity dictionary with issues, prs and comments
        top_contributors: Optional list of top contributors
        hot_issues: Optional list of hot issues/PRs
        start_date: Start date of the report period
        end_date: End date of the report period

    Returns:
        Formatted markdown text suitable for sending to Claude
    """
    issues = activity.get("issues", [])
    prs = activity.get("prs", [])
    comments = activity.get("comments", [])

    output = []

    # Add report header with date range
    if start_date and end_date:
        output.append(
            f"# GitHub Activity Report: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
        )
    else:
        output.append("# GitHub Activity Report")

    output.append("\n## Executive Summary")
    output.append(f"- **Issues Created:** {len(issues)}")
    output.append(f"- **Pull Requests Created:** {len(prs)}")
    output.append(f"- **Comments Added:** {len(comments)}")

    # Add repository stats if we have them
    repos = set()
    for item in issues + prs:
        if "repo_full_name" in item:
            repos.add(item["repo_full_name"])

    if repos:
        output.append(f"- **Repositories:** {len(repos)}")
        output.append("  - " + ", ".join(sorted(repos)))

    # Add top contributors section
    if top_contributors:
        output.append("\n## Top Contributors")
        for i, contributor in enumerate(top_contributors, 1):
            output.append(
                f"**{i}. {contributor['user_login']}** - {contributor['total_activity']} activities"
            )
            contributor_details = []
            if contributor["issue_count"] > 0:
                contributor_details.append(f"Issues: {contributor['issue_count']}")
            if contributor["pr_count"] > 0:
                contributor_details.append(f"PRs: {contributor['pr_count']}")
            if contributor["comment_count"] > 0:
                contributor_details.append(f"Comments: {contributor['comment_count']}")

            output.append("   " + ", ".join(contributor_details))

    # Add hot issues/PRs section
    if hot_issues:
        output.append("\n## Most Active Discussions")
        for i, issue in enumerate(hot_issues, 1):
            issue_type = "PR" if issue.get("is_pull_request", False) else "Issue"
            repo = issue.get("repo_full_name", "unknown/repo")
            number = issue.get("issue_number", 0)
            github_link = f"https://github.com/{repo}/issues/{number}"

            output.append(
                f"**{i}. [{issue_type} #{number}]({github_link})** - {issue.get('issue_title', 'Untitled')}"
            )
            output.append(f"   **Repository:** {repo}")
            output.append(f"   **Activity:** {issue.get('comment_count', 0)} comments")
            output.append("")

    # Format issues with GitHub links
    if issues:
        output.append("\n## New Issues")
        for issue in issues:
            repo = issue.get("repo_full_name", "unknown/repo")
            number = issue.get("number", 0)
            github_link = f"https://github.com/{repo}/issues/{number}"

            output.append(
                f"### [#{number} {issue.get('title', 'Untitled')}]({github_link})"
            )
            output.append(f"**Author:** {issue.get('user_login', 'unknown')}")
            output.append(f"**Repository:** {repo}")
            output.append(f"**Created:** {issue.get('created_at', 'unknown date')}")
            output.append(f"**State:** {issue.get('state', 'unknown')}")
            output.append("\n**Description:**")

            # Truncate very long descriptions
            description = (
                issue.get("body", "") if issue.get("body") else "(No description)"
            )
            if len(description) > 1000:
                description = description[:997] + "..."

            output.append(description)
            output.append("\n" + "-" * 50 + "\n")

    # Format pull requests with GitHub links
    if prs:
        output.append("\n## New Pull Requests")
        for pr in prs:
            repo = pr.get("repo_full_name", "unknown/repo")
            number = pr.get("number", 0)
            github_link = f"https://github.com/{repo}/pull/{number}"

            output.append(
                f"### [#{number} {pr.get('title', 'Untitled')}]({github_link})"
            )
            output.append(f"**Author:** {pr.get('user_login', 'unknown')}")
            output.append(f"**Repository:** {repo}")
            output.append(f"**Created:** {pr.get('created_at', 'unknown date')}")
            output.append(f"**State:** {pr.get('state', 'unknown')}")
            output.append("\n**Description:**")

            # Truncate very long descriptions
            description = pr.get("body", "") if pr.get("body") else "(No description)"
            if len(description) > 1000:
                description = description[:997] + "..."

            output.append(description)
            output.append("\n" + "-" * 50 + "\n")

    # Format comments with GitHub links
    if comments:
        output.append("\n## New Comments")
        for comment in comments:
            issue_or_pr = "PR" if comment.get("is_pull_request", False) else "Issue"
            repo = comment.get("repo_full_name", "unknown/repo")
            number = comment.get("issue_number", 0)
            github_link = f"https://github.com/{repo}/issues/{number}"

            output.append(
                f"### Comment on [{issue_or_pr} #{number}]({github_link}) - {comment.get('issue_title', 'Untitled')}"
            )
            output.append(f"**Author:** {comment.get('user_login', 'unknown')}")
            output.append(f"**Repository:** {repo}")
            output.append(f"**Created:** {comment.get('created_at', 'unknown date')}")

            # Truncate very long comments
            comment_text = (
                comment.get("body", "") if comment.get("body") else "(Empty comment)"
            )
            if len(comment_text) > 500:
                comment_text = comment_text[:497] + "..."

            output.append("\n**Comment:**")
            output.append(comment_text)
            output.append("\n" + "-" * 50 + "\n")

    # Add a references section with all links in one place
    output.append("\n## References")
    output.append("### Issues")
    for issue in issues:
        repo = issue.get("repo_full_name", "unknown/repo")
        number = issue.get("number", 0)
        github_link = f"https://github.com/{repo}/issues/{number}"
        output.append(f"- [#{number} {issue.get('title', 'Untitled')}]({github_link})")

    output.append("\n### Pull Requests")
    for pr in prs:
        repo = pr.get("repo_full_name", "unknown/repo")
        number = pr.get("number", 0)
        github_link = f"https://github.com/{repo}/pull/{number}"
        output.append(f"- [#{number} {pr.get('title', 'Untitled')}]({github_link})")

    return "\n".join(output)


def send_to_claude(report_text, api_key, custom_prompt=None):
    """Send the report to Claude for summarization."""
    try:
        import chatlas
    except ImportError:
        return (
            "Error: chatlas package not installed. Install using 'pip install chatlas'"
        )

    client = chatlas.Client(api_key)

    # Check if we need to chunk the report
    report_chunks = chunk_report_for_claude(report_text)

    if len(report_chunks) > 1:
        print(f"Report split into {len(report_chunks)} chunks for Claude processing")

        all_responses = []
        for i, chunk in enumerate(report_chunks):
            print(f"Processing chunk {i + 1}/{len(report_chunks)}...")

            # Default prompt for chunked reports
            prompt = (
                custom_prompt
                or f"""
            This is chunk {i + 1} of {len(report_chunks)} from a GitHub activity report.
            Please summarize the key activity in this chunk focusing on:
            1. Important issues and PRs
            2. Most active contributors
            3. Common themes or patterns in the activity
            
            Keep your summary concise and actionable.
            """
            )

            try:
                response = client.create_message(
                    messages=[{"role": "user", "content": prompt + "\n\n" + chunk}]
                )
                all_responses.append(
                    f"--- Chunk {i + 1} Summary ---\n\n{response['content'][0]['text']}"
                )
            except Exception as e:
                all_responses.append(f"Error processing chunk {i + 1}: {str(e)}")

        # Combine all responses
        combined_response = "\n\n".join(all_responses)

        # If custom final summary is requested, send combined summaries for final synthesis
        if len(all_responses) > 1:
            try:
                final_prompt = """
                Below are summaries of different chunks of a GitHub activity report.
                Please synthesize these into a single coherent summary that highlights the most important information.
                Focus on key themes, most active contributors, and highest-impact issues/PRs across the whole period.
                """

                final_response = client.create_message(
                    messages=[
                        {
                            "role": "user",
                            "content": final_prompt + "\n\n" + combined_response,
                        }
                    ]
                )

                return f"# Overall Summary\n\n{final_response['content'][0]['text']}\n\n# Individual Chunk Summaries\n\n{combined_response}"
            except Exception as e:
                return (
                    f"{combined_response}\n\nError creating final synthesis: {str(e)}"
                )

        return combined_response
    else:
        # For single chunk reports
        prompt = (
            custom_prompt
            or """
        Please analyze this GitHub activity report and provide a concise summary that:
        1. Highlights the most significant issues and PRs
        2. Identifies the most active contributors and their focus areas
        3. Notes any patterns or themes in the activity
        4. Suggests any areas that might need attention based on the activity

        Your summary should help someone who's been away quickly understand what happened and what might need their attention.
        """
        )

        try:
            response = client.create_message(
                messages=[{"role": "user", "content": prompt + "\n\n" + report_text}]
            )
            return response["content"][0]["text"]
        except Exception as e:
            return f"Error: {str(e)}"


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate GitHub activity reports from GIRD database"
    )
    parser.add_argument(
        "--db",
        type=str,
        default=DEFAULT_DB_PATH,
        help=f"Path to the GIRD SQLite database (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help=f"Number of days to look back (default: {DEFAULT_DAYS})",
    )
    parser.add_argument("--start-date", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument(
        "--repos",
        type=str,
        nargs="*",
        help="Specific repositories to filter by (owner/name format)",
    )
    parser.add_argument(
        "--list-repos",
        action="store_true",
        help="List all repositories in the database",
    )
    parser.add_argument(
        "--output", type=str, help="Output file for the report (default: stdout)"
    )

    # Enhanced reporting options
    parser.add_argument(
        "--top-contributors",
        type=int,
        default=10,
        help="Number of top contributors to include (default: 10, 0 to disable)",
    )
    parser.add_argument(
        "--hot-issues",
        type=int,
        default=5,
        help="Number of most active issues to include (default: 5, 0 to disable)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=20000,
        help="Maximum characters per chunk for large reports (default: 20000)",
    )
    parser.add_argument(
        "--time-chunks",
        type=int,
        help="Split report into time chunks of specified days (optional)",
    )

    # Claude integration
    parser.add_argument(
        "--claude",
        action="store_true",
        help="Send the report to Claude for summarization",
    )
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

        # Check if we should use time-based chunking
        if args.time_chunks and args.time_chunks > 0:
            # Split activity by time chunks
            time_chunks = db.chunk_activity_by_time(activity, args.time_chunks)

            if not time_chunks:
                print("No activity found in the specified time range.")
                return

            # Process each time chunk
            for i, chunk in enumerate(time_chunks, 1):
                chunk_start = chunk["start_date"]
                chunk_end = chunk["end_date"]
                chunk_data = chunk["data"]

                print(f"\n{'=' * 80}")
                print(
                    f"Processing time chunk {i}/{len(time_chunks)}: {chunk_start.strftime('%Y-%m-%d')} to {chunk_end.strftime('%Y-%m-%d')}"
                )
                print(f"{'=' * 80}")

                # Get top contributors and hot issues for this chunk if requested
                top_contributors = None
                if args.top_contributors > 0:
                    top_contributors = db.get_top_contributors(
                        chunk_start, chunk_end, args.repos, args.top_contributors
                    )

                hot_issues = None
                if args.hot_issues > 0:
                    hot_issues = db.get_hot_issues(
                        chunk_start, chunk_end, args.repos, args.hot_issues
                    )

                # Format for output
                chunk_report = format_activity_for_claude(
                    chunk_data, top_contributors, hot_issues, chunk_start, chunk_end
                )

                # Output filename with chunk info
                if args.output:
                    base_name, ext = os.path.splitext(args.output)
                    chunk_filename = f"{base_name}_chunk{i}{ext}"
                    with open(chunk_filename, "w") as f:
                        f.write(chunk_report)
                    print(f"Chunk {i} report written to {chunk_filename}")
                else:
                    print(chunk_report)

                # Send to Claude if requested
                if args.claude:
                    if not args.claude_key:
                        claude_key = os.environ.get("CLAUDE_API_KEY")
                        if not claude_key:
                            print(
                                "Error: Claude API key not provided. Use --claude-key or set CLAUDE_API_KEY environment variable."
                            )
                            return
                    else:
                        claude_key = args.claude_key

                    # Send to Claude and print response
                    print(f"\nSending chunk {i} to Claude for analysis...")
                    claude_response = send_to_claude(
                        chunk_report, claude_key, args.claude_prompt
                    )
                    print(f"\n--- Claude Summary for Chunk {i} ---\n")
                    print(claude_response)
        else:
            # Process the entire date range as a single report

            # Get top contributors and hot issues if requested
            top_contributors = None
            if args.top_contributors > 0:
                top_contributors = db.get_top_contributors(
                    start_date, end_date, args.repos, args.top_contributors
                )

            hot_issues = None
            if args.hot_issues > 0:
                hot_issues = db.get_hot_issues(
                    start_date, end_date, args.repos, args.hot_issues
                )

            # Format for output
            formatted_report = format_activity_for_claude(
                activity, top_contributors, hot_issues, start_date, end_date
            )

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
                        print(
                            "Error: Claude API key not provided. Use --claude-key or set CLAUDE_API_KEY environment variable."
                        )
                        return
                else:
                    claude_key = args.claude_key

                # Use the chunking mechanism for Claude if the report is large
                print("\nSending report to Claude for analysis...")
                claude_response = send_to_claude(
                    formatted_report, claude_key, args.claude_prompt
                )
                print("\n--- Claude Summary ---\n")
                print(claude_response)


if __name__ == "__main__":
    main()
