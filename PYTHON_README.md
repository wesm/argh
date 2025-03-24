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
