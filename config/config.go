package config

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

const (
	// EnvGithubToken is the environment variable name for the GitHub API token
	EnvGithubToken = "ARGH_GITHUB_TOKEN"
)

// Config represents the application configuration
type Config struct {
	// GitHub API token for authentication (optional, can be set via ARGH_GITHUB_TOKEN env var)
	GitHubToken string `json:"github_token"`

	// Path to the SQLite database file
	DatabasePath string `json:"database_path"`

	// List of repositories to sync in the format "owner/name"
	Repositories []string `json:"repositories"`
}

// LoadConfig loads the configuration from a JSON file
func LoadConfig(path string) (*Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("failed to read config file: %w", err)
	}

	var config Config
	if err := json.Unmarshal(data, &config); err != nil {
		return nil, fmt.Errorf("failed to parse config file: %w", err)
	}

	// Check for GitHub token in environment variable
	if envToken := os.Getenv(EnvGithubToken); envToken != "" {
		config.GitHubToken = envToken
	}

	// Set default database path if not specified
	if config.DatabasePath == "" {
		config.DatabasePath = "github_issues.db"
	}

	// Make database path absolute if it's relative
	if !filepath.IsAbs(config.DatabasePath) {
		configDir := filepath.Dir(path)
		config.DatabasePath = filepath.Join(configDir, config.DatabasePath)
	}

	return &config, nil
}

// SaveConfig saves the configuration to a JSON file
func SaveConfig(config *Config, path string) error {
	data, err := json.MarshalIndent(config, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal config: %w", err)
	}

	if err := os.WriteFile(path, data, 0644); err != nil {
		return fmt.Errorf("failed to write config file: %w", err)
	}

	return nil
}

// CreateDefaultConfig creates a default configuration file if it doesn't exist
func CreateDefaultConfig(path string) error {
	// Check if the file already exists
	if _, err := os.Stat(path); err == nil {
		return nil // File exists, don't overwrite
	}

	// Create default config
	config := &Config{
		GitHubToken:  "",
		DatabasePath: "github_issues.db",
		Repositories: []string{"example/repo"},
	}

	// Ensure the directory exists
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return fmt.Errorf("failed to create config directory: %w", err)
	}

	// Save the config
	return SaveConfig(config, path)
}
