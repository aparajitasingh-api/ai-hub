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
	githubToken = os.Getenv("GITHUB_TOKEN")
	githubOrg   = os.Getenv("GITHUB_ORG")
	specPath    = ".oncall/oncall.yaml"
)

func fetchSpec(ctx context.Context, repo string) (*ServiceSpec, error) {
	url := fmt.Sprintf(
		"https://api.github.com/repos/%s/%s/contents/%s",
		githubOrg, repo, specPath,
	)
	req, _ := http.NewRequestWithContext(ctx, "GET", url, nil)
	req.Header.Set("Authorization", "Bearer "+githubToken)
	req.Header.Set("Accept", "application/vnd.github+json")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode == 404 {
		return nil, nil // no spec in this repo, skip
	}
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("github API %d for %s", resp.StatusCode, repo)
	}

	var ghResp struct {
		Content string `json:"content"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&ghResp); err != nil {
		return nil, err
	}

	raw, err := base64.StdEncoding.DecodeString(
		// github wraps content in base64 with newlines
		removeNewlines(ghResp.Content),
	)
	if err != nil {
		return nil, err
	}

	var spec OncallSpec
	if err := yaml.Unmarshal(raw, &spec); err != nil {
		return nil, err
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
	var repos []string
	page := 1
	for {
		url := fmt.Sprintf(
			"https://api.github.com/orgs/%s/repos?per_page=100&page=%d",
			githubOrg, page,
		)
		req, _ := http.NewRequestWithContext(ctx, "GET", url, nil)
		req.Header.Set("Authorization", "Bearer "+githubToken)
		req.Header.Set("Accept", "application/vnd.github+json")

		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			return nil, err
		}
		defer resp.Body.Close()

		var items []struct {
			Name string `json:"name"`
		}
		if err := json.NewDecoder(resp.Body).Decode(&items); err != nil {
			return nil, err
		}
		if len(items) == 0 {
			break
		}
		for _, item := range items {
			repos = append(repos, item.Name)
		}
		page++
	}
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
			spec, err := fetchSpec(ctx, body.Repo)
			if err != nil {
				http.Error(w, err.Error(), http.StatusInternalServerError)
				return
			}
			if spec == nil {
				w.WriteHeader(http.StatusNoContent) // no spec file, skip
				return
			}
			reg.upsert(*spec)
			log.Printf("upserted: %s (repo: %s)", spec.DatadogName, body.Repo)
			json.NewEncoder(w).Encode(map[string]string{"upserted": spec.DatadogName})
			return
		}

		// full rescan
		repos, err := allOrgRepos(ctx)
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}

		var upserted []string
		for _, repo := range repos {
			spec, err := fetchSpec(ctx, repo)
			if err != nil {
				log.Printf("skipping %s: %v", repo, err)
				continue
			}
			if spec == nil {
				continue
			}
			reg.upsert(*spec)
			upserted = append(upserted, spec.DatadogName)
		}

		log.Printf("full rescan: upserted %d services", len(upserted))
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
			http.Error(w, "missing service name", http.StatusBadRequest)
			return
		}
		spec, ok := reg.get(name)
		if !ok {
			http.Error(w, fmt.Sprintf("service '%s' not found", name), http.StatusNotFound)
			return
		}
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
