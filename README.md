# GIRD - GitHub Issues Repo Database

A Go-based tool for scraping GitHub issue activity from multiple repositories into a local SQLite database with support for incremental updates. This allows for offline analysis of issue data across repositories in your organization.

## Core Features

- **Multiple Repository Support**: Track issues from any number of GitHub repositories
- **Incremental Updates**: Efficiently sync only new or updated issues since the last sync
- **Pull Request Support**: Store pull requests alongside issues with proper identification
- **SQLite Database**: Lightweight, zero-configuration database stored in a single file
- **Performance**: Written in Go for excellent performance characteristics
- **Flexible Scheduling**: Run manually or via cron/scheduler for daily/weekly updates
- **Activity Reports**: Generate detailed activity reports using the included Python script

## Installation

### Go Tool Prerequisites

- Go 1.16 or higher
- GitHub Personal Access Token (for private repositories or to avoid rate limits)

### Building the Go Tool from Source

1. Clone the repository:

   ```
   git clone https://github.com/yourusername/gird.git
   cd gird
   ```

2. Build the application:
   ```
   go build -o gird ./cmd
   ```

### Python Report Generator Prerequisites

For the activity report generator, you'll need:

```bash
pip install sqlite3 click requests chatlas
```

## Configuration

The application uses a JSON configuration file. You can create a default configuration file by running:

```
./gird -init
```

This will create a `config.json` file with the following structure:

```json
{
  "github_token": "",
  "database_path": "github_issues.db",
  "repositories": ["example/repo"]
}
```

- `github_token`: Your GitHub Personal Access Token (can be left empty if using the environment variable)
- `database_path`: Path to the SQLite database file (can be absolute or relative to the config file)
- `repositories`: List of repositories to track in the format "owner/name"

### Environment Variables

You can set your GitHub token using the environment variable:

```
export GIRD_GITHUB_TOKEN=your_github_token_here
```

This is the recommended approach as it keeps your token out of configuration files.

## Usage

### Go Tool Usage

#### Adding a Repository

To add a repository to your configuration:

```
./gird -add-repo owner/repository
```

#### Syncing Repositories

To sync all repositories in your configuration:

```
./gird -sync-all
```

To sync a specific repository:

```
./gird -sync-repo owner/repository
```

#### Using a Custom Configuration File

By default, the application looks for `config.json` in the current directory. You can specify a different configuration file:

```
./gird -config /path/to/config.json -sync-all
```

### Python Activity Report Generator

The `gird_activity_report.py` script can generate GitHub activity reports from the GIRD database with the following features:

- Filtering by date range or looking back a specific number of days
- Filtering by specific repositories
- Including top contributors and most active discussions
- Splitting reports by time periods (chunks)
- Sending reports to LLMs for summarization via APIs

#### Basic Usage

```bash
# List available repositories
python gird_activity_report.py list-repositories --db github_issues.db

# Generate a report
python gird_activity_report.py generate-report [OPTIONS]
```

#### Report Generator Options

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

#### Report Generator Examples

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

## Database Schema

The SQLite database contains the following tables:

- `repositories`: Information about tracked repositories
- `users`: GitHub users who created issues, comments, etc.
- `issues`: Issue details including title, body, state, etc. (includes a flag to identify pull requests)
- `comments`: Comments on issues
- `labels`: Issue labels
- `issue_labels`: Many-to-many relationship between issues and labels
- `sync_metadata`: Tracks the last sync time for each repository

The complete database schema is also available in the `sql/schema.sql` file for reference purposes. This file is provided for documentation and for use with external tools, but the application itself uses the embedded schema in the code to ensure it remains a single self-contained binary.

## Enhanced Report Features

The activity report script includes several enhanced features to make GitHub activity reports more informative and manageable:

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

### Using with LLMs

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

## Example SQL Queries

Once you have synced your repositories, you can run SQL queries against the database:

```sql
-- Count issues by state
SELECT state, COUNT(*) FROM issues GROUP BY state;

-- Count issues vs pull requests
SELECT is_pull_request, COUNT(*) FROM issues GROUP BY is_pull_request;

-- Find issues with the most comments
SELECT i.number, i.title, COUNT(c.id) as comment_count
FROM issues i
LEFT JOIN comments c ON i.id = c.issue_id
GROUP BY i.id
ORDER BY comment_count DESC
LIMIT 10;

-- Find issues with specific labels
SELECT i.number, i.title
FROM issues i
JOIN issue_labels il ON i.id = il.issue_id
JOIN labels l ON il.label_id = l.id
WHERE l.name = 'bug';

-- Find open pull requests
SELECT number, title, created_at
FROM issues
WHERE is_pull_request = 1 AND state = 'open'
ORDER BY created_at DESC;
```

## Scheduling Incremental Updates

### Using Cron (Linux/macOS)

To set up a daily sync at 2 AM:

```
0 2 * * * /path/to/gird -config /path/to/config.json -sync-all
```

### Using Task Scheduler (Windows)

1. Open Task Scheduler
2. Create a new Basic Task
3. Set the trigger to daily at your preferred time
4. Set the action to start a program
5. Enter the path to `gird.exe` as the program
6. Add `-config C:\path\to\config.json -sync-all` as arguments

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
