package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"time"

	"github.com/wesm/github-issue-digest/config"
	"github.com/wesm/github-issue-digest/internal/api"
	"github.com/wesm/github-issue-digest/internal/db"
	"github.com/wesm/github-issue-digest/internal/sync"
)

func main() {
	// Define command-line flags
	configPath := flag.String("config", "config.json", "Path to configuration file")
	createConfig := flag.Bool("init", false, "Create a default configuration file if it doesn't exist")
	addRepo := flag.String("add-repo", "", "Add a repository to the configuration (format: owner/name)")
	syncAll := flag.Bool("sync-all", false, "Sync all repositories in the configuration")
	syncRepo := flag.String("sync-repo", "", "Sync a specific repository (format: owner/name)")
	flag.Parse()

	// Create default configuration if requested
	if *createConfig {
		if err := config.CreateDefaultConfig(*configPath); err != nil {
			log.Fatalf("Failed to create default configuration: %v", err)
		}
		log.Printf("Created default configuration at %s", *configPath)
		return
	}

	// Load configuration
	cfg, err := config.LoadConfig(*configPath)
	if err != nil {
		log.Fatalf("Failed to load configuration: %v", err)
	}

	// Add repository if requested
	if *addRepo != "" {
		_, _, err := sync.ParseRepositoryString(*addRepo)
		if err != nil {
			log.Fatalf("Invalid repository format: %v", err)
		}

		// Check if the repository already exists in the configuration
		exists := false
		for _, repo := range cfg.Repositories {
			if repo == *addRepo {
				exists = true
				break
			}
		}

		if !exists {
			cfg.Repositories = append(cfg.Repositories, *addRepo)
			if err := config.SaveConfig(cfg, *configPath); err != nil {
				log.Fatalf("Failed to save configuration: %v", err)
			}
			log.Printf("Added repository %s to configuration", *addRepo)
		} else {
			log.Printf("Repository %s already exists in configuration", *addRepo)
		}

		if !*syncAll && *syncRepo == "" {
			return
		}
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

	// Initialize GitHub client
	client := api.NewGitHubClient(cfg.GitHubToken)

	// Initialize syncer
	syncer := sync.New(database, client)

	// Sync repositories
	ctx := context.Background()
	startTime := time.Now()

	if *syncRepo != "" {
		// Sync a specific repository
		owner, name, err := sync.ParseRepositoryString(*syncRepo)
		if err != nil {
			log.Fatalf("Invalid repository format: %v", err)
		}

		log.Printf("Syncing repository %s/%s", owner, name)
		if err := syncer.SyncRepository(ctx, owner, name); err != nil {
			log.Fatalf("Failed to sync repository %s/%s: %v", owner, name, err)
		}
	} else if *syncAll {
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
	} else {
		// No sync operation requested
		fmt.Println("GIRD - GitHub Issues Repo Digest")
		fmt.Println("--------------------------------")
		fmt.Println("Use -sync-all to sync all repositories in the configuration")
		fmt.Println("Use -sync-repo owner/name to sync a specific repository")
		fmt.Println("Use -add-repo owner/name to add a repository to the configuration")
		fmt.Println("Use -init to create a default configuration file")
		fmt.Println("Use -config path/to/config.json to specify a custom configuration file")
		fmt.Println()
		fmt.Printf("GitHub token can be provided via the %s environment variable\n", config.EnvGithubToken)
		return
	}

	duration := time.Since(startTime)
	log.Printf("Sync completed in %v", duration)
}
