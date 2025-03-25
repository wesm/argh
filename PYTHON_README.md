# GIRD Activity Report Generator

This Python script interfaces with the GIRD (GitHub Issues Repo Database) SQLite database to generate activity reports for specific time ranges. The script can be used to analyze GitHub activity and optionally generate summaries using Large Language Models (LLMs) via APIs.

## Setup

1. Install the required dependencies:

```bash
pip install sqlite3 click requests chatlas
```

2. Make sure you have a GIRD database file. This is created by running the main GIRD tool to sync repositories.

## Activity Reports

The `gird_activity_report.py` script can generate GitHub activity reports from the GIRD database. It supports:

- Filtering by date range or looking back a specific number of days
- Filtering by specific repositories
- Including top contributors and most active discussions
- Splitting reports by time periods (chunks)
- Sending reports to LLMs for summarization via APIs

### Installation

```bash
pip install click requests chatlas
```

### Usage

The script uses Click to provide a more modern and user-friendly command-line interface:

```bash
# List available repositories
python gird_activity_report.py list-repositories --db github_issues.db

# Generate a report
python gird_activity_report.py generate-report [OPTIONS]
```

### Options

```bash
# Common options
--db TEXT                  Path to the GIRD SQLite database (default: github_issues.db)

# List repositories command
python gird_activity_report.py list-repositories [OPTIONS]
  --db TEXT                Path to the GIRD SQLite database (default: github_issues.db)

# Generate report command
python gird_activity_report.py generate-report [OPTIONS]
  --db TEXT                Path to the GIRD SQLite database (default: github_issues.db)
  --days INTEGER           Number of days to look back (default: 7)
  --start-date TEXT        Start date (YYYY-MM-DD)
  --end-date TEXT          End date (YYYY-MM-DD)
  --repos TEXT             Specific repositories to filter by (owner/name format). Can be used multiple times.
  --output TEXT            Output file for the report (default: stdout)
  --top-contributors INTEGER  Number of top contributors to include (default: 10, 0 to disable)
  --hot-issues INTEGER     Number of most active issues to include (default: 5, 0 to disable)
  --chunk-size INTEGER     Maximum characters per chunk for large reports (default: 20000)
  --time-chunks INTEGER    Split report into time chunks of specified days (optional)
  --llm                    Send the report to an LLM for summarization
  --llm-key TEXT           LLM API key
  --llm-model TEXT         Model name to use (default: claude-3.5-sonnet)
  --llm-prompt TEXT        Custom prompt for the LLM
  --dry-run               Show prompts that would be sent to the LLM without making API calls
  --verbose               Display full report content in addition to LLM summary
  --no-llm                Skip LLM summarization and only generate raw activity data
```

### Examples

List all repositories in the database:
```bash
python gird_activity_report.py list-repositories
```

Generate a report for the last 30 days:
```bash
python gird_activity_report.py generate-report --days 30
```

Generate a report for a specific date range:
```bash
python gird_activity_report.py generate-report --start-date 2023-01-01 --end-date 2023-01-31
```

Generate a report for specific repositories:
```bash
python gird_activity_report.py generate-report --repos owner/repo1 --repos owner/repo2
```

Generate a report with custom options and save to file:
```bash
python gird_activity_report.py generate-report --days 14 --top-contributors 5 --hot-issues 3 --output report.md
```

Split activity into weekly chunks:
```bash
python gird_activity_report.py generate-report --days 30 --time-chunks 7
```

Generate a report and send to an LLM for summarization:
```bash
python gird_activity_report.py generate-report --days 14 --llm --llm-key your_api_key
```

Generate a report without LLM summarization:
```bash
python gird_activity_report.py generate-report --days 14 --no-llm
```

Use a different LLM model:
```bash
python gird_activity_report.py generate-report --days 14 --llm --llm-model claude-3-opus-20240229
```

Preview the prompts without making API calls:
```bash
python gird_activity_report.py generate-report --days 14 --dry-run
```

View the full report content:
```bash
python gird_activity_report.py generate-report --days 14 --verbose
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
python gird_activity_report.py generate-report --top-contributors 10
```

This will show the top 10 contributors along with a breakdown of their activity (issues created, PRs submitted, and comments made).

### Most Active Discussions

Identify the "hottest" issues and PRs based on the amount of comment activity:

```bash
python gird_activity_report.py generate-report --hot-issues 5
```

This feature helps quickly identify the most active discussions that may need attention.

### Time-based Chunking

For large date ranges, you can split the report into smaller time chunks:

```bash
# Split a 30-day report into weekly chunks
python gird_activity_report.py generate-report --days 30 --time-chunks 7
```

This will create separate reports for each time chunk, making the information more digestible. When using with `--output`, each chunk will be saved to a separate file.

### GitHub Links

All issues, PRs, and comments in the report now include direct links to their GitHub pages, making it easy to navigate to the original content.

### References Section

A consolidated references section at the end of each report provides a quick way to access all mentioned issues and PRs.

## Using with LLMs

By default, the script will attempt to use an LLM to summarize the GitHub activity data unless the `--no-llm` flag is specified. 
You will need to provide an API key either via the `--llm-key` parameter or by setting the `LLM_API_KEY` environment variable.

To use LLMs for summarizing activity reports, you need to:

1. Get an LLM API key from your chosen provider
2. Install the chatlas package via pip:
   ```bash
   pip install chatlas
   ```

3. Run the activity report script with the `--llm` flag:
   ```bash
   python gird_activity_report.py generate-report --days 7 --llm
   ```

When generating reports, the script now hides the full report content by default to reduce output verbosity. If you want to see both the raw report and the LLM summary, use the `--verbose` flag:

```bash
python gird_activity_report.py generate-report --days 7 --llm --verbose
```

You can also customize the prompt for the LLM:

```bash
python gird_activity_report.py generate-report --llm --llm-prompt "Generate a concise summary of the following GitHub activity with emphasis on high-priority issues"
```

The script now uses Anthropic's Claude 3.5 Sonnet model by default, via the ChatAnthropic interface from the chatlas package. You can specify a different model if needed:

```bash
# Use Claude 3 Opus
python gird_activity_report.py generate-report --llm --llm-model claude-3-opus-20240229

# Use Claude 3 Haiku
python gird_activity_report.py generate-report --llm --llm-model claude-3-haiku-20240307
```

The model names for Claude can be found in the [Anthropic documentation](https://docs.anthropic.com/claude/docs/models-overview).

## Dry Run Mode

The script provides a dry run mode that allows you to preview the prompts that would be sent to the LLM without actually making API calls. This is useful for testing and debugging:

```bash
python gird_activity_report.py generate-report --days 7 --dry-run
```

When using dry run mode:

1. No actual API calls are made
2. The script will display the prompts that would be sent to the LLM
3. You'll see prompt length information and a truncated view of the content
4. You don't need to provide an API key

This allows you to fine-tune your reports and ensure you're getting the right content before consuming API credits.

## Notes

- The script formats GitHub activity in a structured way for LLMs to understand.
- Make sure your database is up-to-date by running GIRD sync before generating reports.
- For large repositories, consider using date filters to avoid overwhelming LLMs with too much data.
