# GIRD - GitHub Issues Repo Database

A Go-based tool for scraping GitHub issue activity from multiple repositories
into a local SQLite database with support for incremental updates. This allows
for offline analysis of issue data across repositories in your organization.

## Features

- **Multiple Repository Support**: Track issues from any number of GitHub repositories
- **Incremental Updates**: Efficiently sync only new or updated issues since the last sync
- **SQLite Database**: Lightweight, zero-configuration database stored in a single file
- **Performance**: Written in Go for excellent performance characteristics
- **Flexible Scheduling**: Run manually or via cron/scheduler for daily/weekly updates

## Installation

### Prerequisites

- Go 1.16 or higher
- GitHub Personal Access Token (for private repositories or to avoid rate limits)

### Building from Source

1. Clone the repository:

   ```
   git clone https://github.com/yourusername/gird.git
   cd gird
   ```

2. Build the application:
   ```
   go build -o gird ./cmd
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

### Adding a Repository

To add a repository to your configuration:

```
./gird -add-repo owner/repository
```

### Syncing Repositories

To sync all repositories in your configuration:

```
./gird -sync-all
```

To sync a specific repository:

```
./gird -sync-repo owner/repository
```

### Using a Custom Configuration File

By default, the application looks for `config.json` in the current directory. You can specify a different configuration file:

```
./gird -config /path/to/config.json -sync-all
```

## Database Schema

The SQLite database contains the following tables:

- `repositories`: Information about tracked repositories
- `users`: GitHub users who created issues, comments, etc.
- `issues`: Issue details including title, body, state, etc.
- `comments`: Comments on issues
- `labels`: Issue labels
- `issue_labels`: Many-to-many relationship between issues and labels
- `sync_metadata`: Tracks the last sync time for each repository

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

## Example Queries

Once you have synced your repositories, you can run SQL queries against the database:

```sql
-- Count issues by state
SELECT state, COUNT(*) FROM issues GROUP BY state;

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
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
