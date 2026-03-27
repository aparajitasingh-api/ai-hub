package main

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
	"sync"

	"gopkg.in/yaml.v3"
)

// --- types ---

type OncallSpec struct {
	Service ServiceSpec `yaml:"service"`
}

type ServiceSpec struct {
	DatadogName string     `yaml:"datadog_name" json:"datadog_name"`
	GithubRepo  string     `yaml:"github_repo"  json:"github_repo"`
	Kibana      KibanaSpec `yaml:"kibana"       json:"kibana"`
	VM          VMSpec     `yaml:"victoria_metrics" json:"victoria_metrics"`
	OncallChan  string     `yaml:"oncall_channel" json:"oncall_channel"`
	OwnerTeam   string     `yaml:"owner_team"   json:"owner_team"`
}

type KibanaSpec struct {
	BaseURL      string `yaml:"base_url"       json:"base_url"`
	IndexPattern string `yaml:"index_pattern"  json:"index_pattern"`
	DefaultQuery string `yaml:"default_query"  json:"default_query"`
}

type VMSpec struct {
	BaseURL      string `yaml:"base_url"      json:"base_url"`
	DefaultQuery string `yaml:"default_query" json:"default_query"`
}

// --- registry ---

type Registry struct {
	mu       sync.RWMutex
	services map[string]ServiceSpec // keyed by datadog_name
}

func (r *Registry) upsert(spec ServiceSpec) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.services[spec.DatadogName] = spec
}

func (r *Registry) get(name string) (ServiceSpec, bool) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	s, ok := r.services[name]
	return s, ok
}

// --- github ---

var (
	githubToken  = os.Getenv("GITHUB_TOKEN")
	githubOrg    = os.Getenv("GITHUB_ORG")
	specFileName = ".oncall/oncall.yaml"
)

// fetchSpecs returns all service specs found in a repo.
// It uses the Git Trees API with recursive mode to find every
// path ending in .oncall/oncall.yaml — at the root or nested
// inside subdirectories (monorepo support).
func fetchSpecs(ctx context.Context, repo string) ([]ServiceSpec, error) {
	log.Printf("fetchSpecs: scanning %s/%s for spec files", githubOrg, repo)

	paths, err := findSpecPaths(ctx, repo)
	if err != nil {
		return nil, err
	}
	if len(paths) == 0 {
		log.Printf("fetchSpecs: %s has no spec files", repo)
		return nil, nil
	}
	log.Printf("fetchSpecs: found %d spec file(s) in %s: %v", len(paths), repo, paths)

	var specs []ServiceSpec
	for _, path := range paths {
		spec, err := fetchFileAndParse(ctx, repo, path)
		if err != nil {
			log.Printf("fetchSpecs: failed to parse %s in %s: %v", path, repo, err)
			continue
		}
		if spec.GithubRepo == "" {
			spec.GithubRepo = repo
		}
		specs = append(specs, *spec)
		log.Printf("fetchSpecs: parsed %s -> datadog_name=%s", path, spec.DatadogName)
	}
	return specs, nil
}

// findSpecPaths uses the Git Trees API (recursive) to list all
// file paths matching .oncall/oncall.yaml anywhere in the repo tree.
func findSpecPaths(ctx context.Context, repo string) ([]string, error) {
	url := fmt.Sprintf(
		"https://api.github.com/repos/%s/%s/git/trees/HEAD?recursive=1",
		githubOrg, repo,
	)
	req, _ := http.NewRequestWithContext(ctx, "GET", url, nil)
	req.Header.Set("Authorization", "Bearer "+githubToken)
	req.Header.Set("Accept", "application/vnd.github+json")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		log.Printf("findSpecPaths: request failed for %s: %v", repo, err)
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode == 404 || resp.StatusCode == 409 {
		// 404 = repo not found or empty, 409 = empty repo (no commits)
		log.Printf("findSpecPaths: %s returned %d, skipping", repo, resp.StatusCode)
		return nil, nil
	}
	if resp.StatusCode != 200 {
		log.Printf("findSpecPaths: unexpected status %d for %s", resp.StatusCode, repo)
		return nil, fmt.Errorf("github trees API %d for %s", resp.StatusCode, repo)
	}

	var tree struct {
		Tree []struct {
			Path string `json:"path"`
			Type string `json:"type"`
		} `json:"tree"`
		Truncated bool `json:"truncated"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&tree); err != nil {
		log.Printf("findSpecPaths: decode failed for %s: %v", repo, err)
		return nil, err
	}
	if tree.Truncated {
		log.Printf("findSpecPaths: warning: tree was truncated for %s, some specs may be missed", repo)
	}

	var paths []string
	for _, entry := range tree.Tree {
		if entry.Type != "blob" {
			continue
		}
		if strings.HasSuffix(entry.Path, specFileName) {
			paths = append(paths, entry.Path)
		}
	}
	return paths, nil
}

// fetchFileAndParse fetches a single file via the Contents API and
// parses it as an OncallSpec YAML.
func fetchFileAndParse(ctx context.Context, repo, path string) (*ServiceSpec, error) {
	log.Printf("fetchFileAndParse: fetching %s from %s/%s", path, githubOrg, repo)
	url := fmt.Sprintf(
		"https://api.github.com/repos/%s/%s/contents/%s",
		githubOrg, repo, path,
	)
	req, _ := http.NewRequestWithContext(ctx, "GET", url, nil)
	req.Header.Set("Authorization", "Bearer "+githubToken)
	req.Header.Set("Accept", "application/vnd.github+json")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("github API %d for %s/%s", resp.StatusCode, repo, path)
	}

	var ghResp struct {
		Content string `json:"content"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&ghResp); err != nil {
		return nil, fmt.Errorf("decode response for %s: %w", path, err)
	}

	raw, err := base64.StdEncoding.DecodeString(removeNewlines(ghResp.Content))
	if err != nil {
		return nil, fmt.Errorf("base64 decode for %s: %w", path, err)
	}

	var spec OncallSpec
	if err := yaml.Unmarshal(raw, &spec); err != nil {
		return nil, fmt.Errorf("yaml parse for %s: %w", path, err)
	}
	return &spec.Service, nil
}

func removeNewlines(s string) string {
	out := make([]byte, 0, len(s))
	for i := 0; i < len(s); i++ {
		if s[i] != '\n' {
			out = append(out, s[i])
		}
	}
	return string(out)
}

func allOrgRepos(ctx context.Context) ([]string, error) {
	log.Printf("allOrgRepos: listing repos for org %s", githubOrg)
	var repos []string
	page := 1
	for {
		log.Printf("allOrgRepos: fetching page %d", page)
		url := fmt.Sprintf(
			"https://api.github.com/orgs/%s/repos?per_page=100&page=%d",
			githubOrg, page,
		)
		req, _ := http.NewRequestWithContext(ctx, "GET", url, nil)
		req.Header.Set("Authorization", "Bearer "+githubToken)
		req.Header.Set("Accept", "application/vnd.github+json")

		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			log.Printf("allOrgRepos: request failed on page %d: %v", page, err)
			return nil, err
		}
		defer resp.Body.Close()

		var items []struct {
			Name string `json:"name"`
		}
		if err := json.NewDecoder(resp.Body).Decode(&items); err != nil {
			log.Printf("allOrgRepos: failed to decode page %d: %v", page, err)
			return nil, err
		}
		if len(items) == 0 {
			log.Printf("allOrgRepos: no more repos, done at page %d", page)
			break
		}
		log.Printf("allOrgRepos: page %d returned %d repos", page, len(items))
		for _, item := range items {
			repos = append(repos, item.Name)
		}
		page++
	}
	log.Printf("allOrgRepos: found %d repos total", len(repos))
	return repos, nil
}

// --- handlers ---

func refreshHandler(reg *Registry) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "POST only", http.StatusMethodNotAllowed)
			return
		}

		var body struct {
			Repo string `json:"repo"` // optional: single repo upsert
		}
		data, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(data, &body)

		ctx := r.Context()

		if body.Repo != "" {
			// single repo upsert (called by Jenkins on deploy)
			log.Printf("refresh: single repo upsert requested for %s", body.Repo)
			specs, err := fetchSpecs(ctx, body.Repo)
			if err != nil {
				log.Printf("refresh: single repo upsert failed for %s: %v", body.Repo, err)
				http.Error(w, err.Error(), http.StatusInternalServerError)
				return
			}
			if len(specs) == 0 {
				log.Printf("refresh: %s has no spec files, returning 204", body.Repo)
				w.WriteHeader(http.StatusNoContent)
				return
			}
			var names []string
			for _, spec := range specs {
				reg.upsert(spec)
				names = append(names, spec.DatadogName)
				log.Printf("refresh: upserted %s (repo: %s)", spec.DatadogName, body.Repo)
			}
			json.NewEncoder(w).Encode(map[string]any{"upserted": names, "count": len(names)})
			return
		}

		// full rescan
		log.Printf("refresh: starting full org rescan")
		repos, err := allOrgRepos(ctx)
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}

		var upserted []string
		total := len(repos)
		for i, repo := range repos {
			specs, err := fetchSpecs(ctx, repo)
			if err != nil {
				log.Printf("[%d/%d] skipping %s: %v", i+1, total, repo, err)
				continue
			}
			if len(specs) == 0 {
				log.Printf("[%d/%d] %s: no spec files", i+1, total, repo)
				continue
			}
			for _, spec := range specs {
				reg.upsert(spec)
				upserted = append(upserted, spec.DatadogName)
			}
			log.Printf("[%d/%d] %s: upserted %d service(s)", i+1, total, repo, len(specs))
		}

		log.Printf("full rescan: upserted %d services from %d repos", len(upserted), total)
		json.NewEncoder(w).Encode(map[string]any{
			"upserted": upserted,
			"count":    len(upserted),
		})
	}
}

func serviceHandler(reg *Registry) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			http.Error(w, "GET only", http.StatusMethodNotAllowed)
			return
		}
		// expects /service/{datadog_service_name}
		name := r.PathValue("name") // Go 1.22+
		if name == "" {
			log.Printf("service: request with missing service name")
			http.Error(w, "missing service name", http.StatusBadRequest)
			return
		}
		log.Printf("service: looking up %s", name)
		spec, ok := reg.get(name)
		if !ok {
			log.Printf("service: %s not found in registry", name)
			http.Error(w, fmt.Sprintf("service '%s' not found", name), http.StatusNotFound)
			return
		}
		log.Printf("service: returning spec for %s (repo: %s, team: %s)", name, spec.GithubRepo, spec.OwnerTeam)
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(spec)
	}
}

// --- main ---

func main() {
	reg := &Registry{services: make(map[string]ServiceSpec)}

	mux := http.NewServeMux()
	mux.HandleFunc("POST /refresh", refreshHandler(reg))
	mux.HandleFunc("GET /service/{name}", serviceHandler(reg))

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	log.Printf("listening on :%s", port)
	log.Fatal(http.ListenAndServe(":"+port, mux))
}
