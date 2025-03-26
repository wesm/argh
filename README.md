# argh: Activity Reporter for GitHub

A comprehensive GitHub activity tracking and reporting solution consisting of two integrated components:

1. **argh-sync**: A Go-based tool for scraping GitHub issue activity from multiple repositories into a local SQLite database with support for incremental updates
2. **argh.py**: A Python-based activity report generator that creates detailed, customizable reports with optional LLM-powered analysis

Together, these tools allow for efficient tracking, offline analysis, and insightful reporting of GitHub activity across your repositories.

## Core Features

### Database & Synchronization (argh-sync)

- **Multiple Repository Support**: Track issues from any number of GitHub repositories
- **Incremental Updates**: Efficiently sync only new or updated issues since the last sync
- **Pull Request Support**: Store pull requests alongside issues with proper identification
- **SQLite Database**: Lightweight, zero-configuration database stored in a single file

### Activity Reporting (argh.py)

- **Flexible Date Ranges**: Generate reports for any time period with precise date control
- **Repository Filtering**: Focus on specific repositories or analyze activity across all
- **Contributor Analytics**: Track and rank contributors based on various activity metrics
- **LLM-Powered Insights**: Optional AI analysis of significant developments with technical context and implications

### System Features

- **Performance**: Written in Go (sync) and Python (reporting) for excellent performance characteristics
- **Flexible Scheduling**: Run manual updates or automate via cron/scheduler for regular reports
- **Markdown Output**: Generate clean, formatted reports with clickable links to issues and PRs

## Installation

### Go Tool Prerequisites

- Go 1.16 or higher
- GitHub Personal Access Token (for private repositories or to avoid rate limits)

### Building the Go Tool from Source

1. Clone the repository:

```
git clone https://github.com/yourusername/argh.git
cd argh
```

2. Build the application:

```
go build -o argh-sync ./cmd
```

### Python Report Generator Prerequisites

For the activity report generator, you'll need:

```bash
pip install sqlite3 click requests chatlas
```

## Configuration

The application uses a JSON configuration file. You can create a default configuration file by running:

```
./argh-sync -init
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
export ARGH_GITHUB_TOKEN=your_github_token_here
```

This is the recommended approach as it keeps your token out of configuration files.

## Usage

### Go Tool Usage

#### Adding a Repository

To add a repository to your configuration:

```
./argh-sync -add-repo owner/repository
```

#### Syncing Repositories

To sync all repositories in your configuration:

```
./argh-sync -sync-all
```

To sync a specific repository:

```
./argh-sync -sync-repo owner/repository
```

#### Using a Custom Configuration File

By default, the application looks for `config.json` in the current directory. You can specify a different configuration file:

```
./argh-sync -config /path/to/config.json -sync-all
```

### Python Activity Report Generator

The `argh.py` script can generate GitHub activity reports from the database with the following features:

- Filtering by date range or looking back a specific number of days
- Filtering by specific repositories
- Including all contributors with accurate activity counts
- Generating markdown-formatted reports with clickable links
- Advanced LLM analysis focusing on significant developments and their implications

#### Basic Usage

```bash
python argh.py --days 7
```

#### Report Generator Options

```
Options:
  --db-path TEXT               Path to SQLite database (default: github_issues.db)
  --output TEXT                Path to save the report (default: print to stdout)
  --days INTEGER               Number of days to include in the report (default: 7)
  --start-date TEXT            Start date for the report (format: YYYY-MM-DD). Overrides --days if specified.
  --end-date TEXT              End date for the report (format: YYYY-MM-DD). Defaults to today if not specified.
  --repositories TEXT          Comma-separated list of repositories to include (default: all)
  --llm-api-key TEXT           API key for the LLM (default: LLM_API_KEY environment variable)
  --llm-model TEXT             Model name for the LLM (default: claude-3-7-sonnet-latest)
  --llm-provider [anthropic|openai]
                               LLM provider to use (default: anthropic)
  --dry-run                    Don't actually send to LLM, just show what would be sent
  --custom-prompt TEXT         Custom prompt to use for the LLM (overrides the default)
  --verbose                    Include additional details like comment bodies in the report
  --help                       Show this message and exit.
```

#### Report Generator Examples

Generate a report for the last 7 days:

```bash
python argh.py
```

Generate a report for a specific date range with end of day inclusivity:

```bash
python argh.py --start-date 2025-03-15 --end-date 2025-03-25
```

Generate a report for specific repositories:

```bash
python argh.py --repositories "owner/repo1,owner/repo2"
```

Generate a report and analyze with OpenAI:

```bash
python argh.py --llm-provider openai --llm-model gpt-4-turbo
```

Generate a detailed verbose report (includes comment bodies):

```bash
python argh.py --verbose --output full_report.md
```

Preview the LLM prompt without making API calls:

```bash
python argh.py --dry-run
```

#### LLM-Enhanced Reports

The activity report can use LLM capabilities (Claude or OpenAI) to generate insightful analysis of the GitHub activity. The enhanced reports include:

1. **Comprehensive Metrics**: Accurate counts of issues, PRs, comments and complete contributor statistics
2. **Significant Developments Analysis**: In-depth analysis of important changes including:
   - Explanation of WHY changes are being made and problems being solved
   - Technical insights and architectural implications
   - Connection of individual changes to broader themes or project goals
   - Future impact assessment of current work

To generate these enhanced reports, ensure you have:

1. An API key for either Anthropic (Claude) or OpenAI
2. The `chatlas` Python package installed:
   ```bash
   pip install chatlas
   ```

Set your API key via environment variable:

```bash
export LLM_API_KEY=your_api_key
```

Or provide it directly:

```bash
python argh.py --llm-api-key your_api_key
```

## Advanced Features

### Contributor Analysis

The argh.py script automatically includes a ranked list of all contributors in the report:

```bash
python argh.py
```

This will show all contributors along with a breakdown of their activity (issues created, PRs submitted, and comments made).

### Date Range Customization

Generate a report for a specific custom date range:

```bash
python argh.py --start-date 2025-03-15 --end-date 2025-03-25
```

The end dates include activity until the end of the day (23:59:59) and start dates begin at the start of the day (00:00:00).

### Repository Filtering

Focus on specific repositories by providing a comma-separated list:

```bash
python argh.py --repositories "owner/repo1,owner/repo2"
```

### Rich Output Options

Generate a detailed verbose report that includes comment bodies:

```bash
python argh.py --verbose --output full_report.md
```

### AI-powered Analysis

For more insightful analysis, you can use LLM capabilities:

1. Install the chatlas package:
   ```bash
   pip install chatlas
   ```

2. Run the activity report script with LLM parameters:
   ```bash
   python argh.py --llm-api-key your_api_key
   ```

3. Preview the LLM prompt without making API calls:
   ```bash
   python argh.py --dry-run
   ```

4. Use different LLM providers:
   ```bash
   python argh.py --llm-provider openai --llm-model gpt-4-turbo
   ```

## Database Schema

The SQLite database contains the following tables:

- `repositories`: Information about each repository being tracked
- `users`: GitHub users who have created issues, PRs, or comments
- `issues`: Issues and pull requests (with `is_pull_request` flag)
- `comments`: Comments on issues and pull requests
- `labels`: Issue/PR labels
- `issue_labels`: Mapping between issues and labels
- `sync_metadata`: Information about the last sync time for each repository

## Example SQL Queries

Here are some useful SQL queries you can run directly on the database:

### Find Most Active Issues

```sql
SELECT
    issues.number,
    issues.title,
    repositories.full_name as repo,
    COUNT(comments.id) as comment_count
FROM
    issues
JOIN
    repositories ON issues.repository_id = repositories.id
LEFT JOIN
    comments ON issues.id = comments.issue_id
GROUP BY
    issues.id
ORDER BY
    comment_count DESC
LIMIT 10;
```

### Find Most Active Contributors

```sql
SELECT
    users.login,
    COUNT(DISTINCT CASE WHEN issues.is_pull_request = 0 THEN issues.id ELSE NULL END) as issues_opened,
    COUNT(DISTINCT CASE WHEN issues.is_pull_request = 1 THEN issues.id ELSE NULL END) as prs_opened,
    COUNT(comments.id) as comments_made
FROM
    users
LEFT JOIN
    issues ON users.id = issues.user_id
LEFT JOIN
    comments ON users.id = comments.user_id
GROUP BY
    users.id
ORDER BY
    (issues_opened + prs_opened + comments_made) DESC
LIMIT 10;
```

### Track Issue Resolution Time

```sql
SELECT
    repositories.full_name as repo,
    issues.number,
    issues.title,
    issues.created_at,
    issues.closed_at,
    julianday(issues.closed_at) - julianday(issues.created_at) as days_to_resolve
FROM
    issues
JOIN
    repositories ON issues.repository_id = repositories.id
WHERE
    issues.state = 'closed'
    AND issues.is_pull_request = 0
ORDER BY
    days_to_resolve DESC
LIMIT 20;
```
