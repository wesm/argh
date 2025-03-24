# GIRD Activity Report Generator

This Python script interfaces with the GIRD (GitHub Issues Repo Database) SQLite database to generate activity reports for specific time ranges. The script can be used to analyze GitHub activity and optionally generate summaries using Claude AI via the chatlas package.

## Setup

1. Install the required dependencies:

```bash
pip install sqlite3 chatlas
```

2. Make sure you have a GIRD database file. This is created by running the main GIRD tool to sync repositories.

## Usage

The script provides several options to customize your activity report:

```bash
python gird_activity_report.py [options]
```

### Options

- `--db PATH`: Path to the GIRD SQLite database (default: `github_issues.db`)
- `--days N`: Number of days to look back (default: 7)
- `--start-date DATE`: Start date in YYYY-MM-DD format
- `--end-date DATE`: End date in YYYY-MM-DD format
- `--repos REPO [REPO ...]`: Specific repositories to filter by (in owner/name format)
- `--list-repos`: List all repositories in the database
- `--output FILE`: Output file for the report (default: print to stdout)
- `--top-contributors N`: Number of top contributors to include (default: 10, 0 to disable)
- `--hot-issues N`: Number of most active issues to include (default: 5, 0 to disable)
- `--chunk-size N`: Maximum characters per chunk for large reports (default: 20000)
- `--time-chunks N`: Split report into time chunks of specified days (optional)
- `--claude`: Send the report to Claude for summarization
- `--claude-key KEY`: Claude API key
- `--claude-prompt PROMPT`: Custom prompt for Claude

### Examples

List all repositories in the database:
```bash
python gird_activity_report.py --list-repos --db github_issues.db
```

Generate a report for the last 7 days:
```bash
python gird_activity_report.py --db github_issues.db
```

Generate a report for a specific date range:
```bash
python gird_activity_report.py --start-date 2025-03-01 --end-date 2025-03-15
```

Filter by specific repositories:
```bash
python gird_activity_report.py --repos posit-dev/positron wesm/pandas
```

Save the report to a file:
```bash
python gird_activity_report.py --output activity_report.md
```

Generate a report with top 5 contributors and top 10 hot issues:
```bash
python gird_activity_report.py --top-contributors 5 --hot-issues 10
```

Break a large time period into weekly chunks:
```bash
python gird_activity_report.py --days 30 --time-chunks 7
```

## Enhanced Report Features

The activity report script now includes several enhanced features to make GitHub activity reports more informative and manageable:

### Executive Summary

Each report begins with an executive summary that provides high-level statistics about the activity in the specified time period, including:
- Number of issues created
- Number of pull requests created
- Number of comments added
- List of repositories included

### Top Contributors

Include a ranked list of the most active contributors in the report:

```bash
python gird_activity_report.py --top-contributors 10
```

This will show the top 10 contributors along with a breakdown of their activity (issues created, PRs submitted, and comments made).

### Most Active Discussions

Identify the "hottest" issues and PRs based on the amount of comment activity:

```bash
python gird_activity_report.py --hot-issues 5
```

This feature helps quickly identify the most active discussions that may need attention.

### Time-based Chunking

For large date ranges, you can split the report into smaller time chunks:

```bash
# Split a 30-day report into weekly chunks
python gird_activity_report.py --days 30 --time-chunks 7
```

This will create separate reports for each time chunk, making the information more digestible. When using with `--output`, each chunk will be saved to a separate file.

### GitHub Links

All issues, PRs, and comments in the report now include direct links to their GitHub pages, making it easy to navigate to the original content.

### References Section

A consolidated references section at the end of each report provides a quick way to access all mentioned issues and PRs.

## Using with Claude AI

To use Claude AI for summarizing activity reports, you need to:

1. Get a Claude API key from [Anthropic](https://www.anthropic.com/)
2. Install the `chatlas` package: `pip install chatlas`
3. Use the `--claude` flag with your API key:

```bash
# Using command line argument
python gird_activity_report.py --claude --claude-key your_api_key

# Or using environment variable
export CLAUDE_API_KEY=your_api_key
python gird_activity_report.py --claude
```

You can also customize the prompt for Claude:

```bash
python gird_activity_report.py --claude --claude-prompt "Generate a concise summary of the following GitHub activity with emphasis on high-priority issues"
```

## Customizing Claude with Chatlas

The `chatlas` package provides a simple interface to Claude's API. The script uses a basic implementation, but you can customize it further:

1. Advanced message formatting:
```python
import chatlas

client = chatlas.Client(api_key)
messages = [
    {"role": "user", "content": "Please analyze this GitHub activity: " + activity_data}
]
response = client.create_message(messages=messages)
```

2. Tool use with Claude:
```python
# Define tools (functions) that Claude can use
tools = [
    {
        "name": "search_issues",
        "description": "Search for GitHub issues",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "repository": {"type": "string"}
            },
            "required": ["query"]
        }
    }
]

# Enable tool use in the client
client = chatlas.Client(api_key)
response = client.send_message(
    "Find all issues related to performance",
    tools=tools,
    tool_choice={"type": "auto"}
)
```

For more details on tool use with Claude, refer to the [Anthropic documentation](https://docs.anthropic.com/claude/docs/tool-use).

## Notes

- The script formats GitHub activity in a structured way for Claude to understand.
- Make sure your database is up-to-date by running GIRD sync before generating reports.
- For large repositories, consider using date filters to avoid overwhelming Claude with too much data.
