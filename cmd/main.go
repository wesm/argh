package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"os"
	"time"

	"github.com/wesm/github-issue-digest/config"
	"github.com/wesm/github-issue-digest/internal/db"
	"github.com/wesm/github-issue-digest/internal/sync"
)

func main() {
	// Define command-line flags
	var (
		configPath      string
		createConfig    bool
		addRepo         string
		syncAll         bool
		syncRepo        string
		workers         int
	)
	flag.StringVar(&configPath, "config", "config.json", "Path to configuration file")
	flag.BoolVar(&createConfig, "init", false, "Create a default configuration file if it doesn't exist")
	flag.StringVar(&addRepo, "add-repo", "", "Add a repository to the configuration (format: owner/name)")
	flag.BoolVar(&syncAll, "sync-all", false, "Sync all repositories in the configuration")
	flag.StringVar(&syncRepo, "sync-repo", "", "Sync a specific repository (format: owner/name)")
	flag.IntVar(&workers, "workers", 5, "Number of worker goroutines for syncing repositories")
	flag.Parse()

	// Create default configuration if requested
	if createConfig {
		if err := config.CreateDefaultConfig(configPath); err != nil {
			log.Fatalf("Failed to create default configuration: %v", err)
		}
		log.Printf("Created default configuration at %s", configPath)
		return
	}

	// Check if we need to perform any operations that require the config
	needConfig := addRepo != "" || syncAll || syncRepo != ""

	// Only load configuration if needed
	var cfg *config.Config
	var err error

	if needConfig {
		// Load configuration
		cfg, err = config.LoadConfig(configPath)
		if err != nil {
			log.Fatalf("Failed to load configuration: %v", err)
		}
	}

	// Add repository if requested
	if addRepo != "" {
		_, _, err := sync.ParseRepositoryString(addRepo)
		if err != nil {
			log.Fatalf("Invalid repository format: %v", err)
		}

		// Check if the repository already exists in the configuration
		exists := false
		for _, repo := range cfg.Repositories {
			if repo == addRepo {
				exists = true
				break
			}
		}

		if !exists {
			cfg.Repositories = append(cfg.Repositories, addRepo)
			if err := config.SaveConfig(cfg, configPath); err != nil {
				log.Fatalf("Failed to save configuration: %v", err)
			}
			log.Printf("Added repository %s to configuration", addRepo)
		} else {
			log.Printf("Repository %s already exists in configuration", addRepo)
		}

		if !syncAll && syncRepo == "" {
			return
		}
	}

	// If no operation flags are set, show help and exit
	if !needConfig {
		// No sync operation requested - show help message
		fmt.Println("GIRD - GitHub Issues Repo Database")
		fmt.Println("==================================")
		fmt.Println("A tool for syncing GitHub issues and pull requests to a local SQLite database.")
		fmt.Println()
		fmt.Println("USAGE:")
		fmt.Println("  ./gird [options]")
		fmt.Println()
		fmt.Println("OPTIONS:")
		fmt.Println("  -init                   Create a default configuration file")
		fmt.Println("  -config <path>          Specify a custom configuration file (default: config.json)")
		fmt.Println("  -add-repo <owner/name>  Add a repository to the configuration")
		fmt.Println("  -sync-all               Sync all repositories in the configuration")
		fmt.Println("  -sync-repo <owner/name> Sync a specific repository")
		fmt.Println("  -workers <num>          Number of worker goroutines for syncing repositories (default: 5)")
		fmt.Println()
		fmt.Println("EXAMPLES:")
		fmt.Println("  ./gird -init                           # Create default config.json")
		fmt.Println("  ./gird -add-repo golang/go             # Add the Go repository to config")
		fmt.Println("  ./gird -sync-repo golang/go            # Sync only the Go repository")
		fmt.Println("  ./gird -sync-all                       # Sync all configured repositories")
		fmt.Println("  ./gird -config custom.json -sync-all   # Use custom config file and sync all repos")
		fmt.Println()
		fmt.Println("CONFIGURATION:")
		fmt.Printf("  GitHub token can be provided via the %s environment variable\n", config.EnvGithubToken)
		fmt.Println("  or in the config.json file.")
		fmt.Println()
		fmt.Println("DATABASE:")
		fmt.Println("  The SQLite database will be created at the path specified in the config file.")
		fmt.Println("  Default: github_issues.db in the current directory")
		return
	}

	// Initialize database
	database, err := db.New(cfg.DatabasePath)
	if err != nil {
		log.Fatalf("Failed to connect to database: %v", err)
	}
	defer database.Close()

	if err := database.Initialize(); err != nil {
		log.Fatalf("Failed to initialize database: %v", err)
	}

	// Get GitHub token from environment variable or configuration
	token := os.Getenv("GIRD_GITHUB_TOKEN")
	if token == "" {
		token = cfg.GitHubToken
	}
	if token == "" {
		log.Fatalf("GitHub token not found. Please set the GIRD_GITHUB_TOKEN environment variable or add it to the configuration file.")
	}

	// Initialize syncer - always use REST API
	syncer := sync.NewSyncer(database, token, workers, false)

	// Sync repositories
	ctx := context.Background()
	startTime := time.Now()

	if syncRepo != "" {
		// Sync a specific repository
		owner, name, err := sync.ParseRepositoryString(syncRepo)
		if err != nil {
			log.Fatalf("Invalid repository format: %v", err)
		}

		log.Printf("Syncing repository %s/%s", owner, name)
		if err := syncer.SyncRepository(ctx, owner, name); err != nil {
			log.Fatalf("Failed to sync repository %s/%s: %v", owner, name, err)
		}
	} else if syncAll {
		// Sync all repositories
		log.Printf("Syncing %d repositories", len(cfg.Repositories))
		for _, repoStr := range cfg.Repositories {
			owner, name, err := sync.ParseRepositoryString(repoStr)
			if err != nil {
				log.Printf("Skipping invalid repository %s: %v", repoStr, err)
				continue
			}

			log.Printf("Syncing repository %s/%s", owner, name)
			if err := syncer.SyncRepository(ctx, owner, name); err != nil {
				log.Printf("Failed to sync repository %s/%s: %v", owner, name, err)
				// Continue with other repositories even if one fails
				continue
			}
		}
	}

	duration := time.Since(startTime)
	log.Printf("Sync completed in %v", duration)
}
