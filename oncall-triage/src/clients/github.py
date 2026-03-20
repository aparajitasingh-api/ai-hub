import base64
import logging

from src.config import GitHubSettings
from src.models.rca import CodeReference

from .base import BaseAsyncClient

logger = logging.getLogger(__name__)


class GitHubClient(BaseAsyncClient):
    """Client for GitHub API -- code search and file content retrieval."""

    def __init__(self, settings: GitHubSettings):
        super().__init__(
            base_url="https://api.github.com",
            headers={
                "Authorization": f"Bearer {settings.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        self._settings = settings

    async def search_code(
        self,
        query: str,
        repos: list[str] | None = None,
        max_results: int = 5,
    ) -> list[dict]:
        """Search for code across repositories.

        Args:
            query: Search term (function name, error string, etc.).
            repos: Repos to scope the search (e.g. ["org/repo1"]).
                   Falls back to configured default_repos.
            max_results: Max results to return.
        """
        scope_repos = repos or [
            f"{self._settings.org}/{r}" for r in self._settings.repos_list
        ]
        repo_qualifier = " ".join(f"repo:{r}" for r in scope_repos)
        full_query = f"{query} {repo_qualifier}".strip()

        logger.info("GitHub code search: %s", full_query)
        data = await self._get(
            "/search/code",
            params={"q": full_query, "per_page": max_results},
        )
        return data.get("items", [])

    async def get_file_content(
        self,
        owner: str,
        repo: str,
        path: str,
        ref: str = "main",
    ) -> str:
        """Fetch raw file content from a repository."""
        data = await self._get(
            f"/repos/{owner}/{repo}/contents/{path}",
            params={"ref": ref},
        )
        content = data.get("content", "")
        return base64.b64decode(content).decode("utf-8")

    async def find_relevant_code(
        self,
        metric_name: str,
        service_name: str | None,
        error_patterns: list[str],
    ) -> list[CodeReference]:
        """Search GitHub for code related to an alert's signals.

        Searches by metric name, service name, and the top error
        patterns extracted from logs.
        """
        references: list[CodeReference] = []
        seen_paths: set[str] = set()

        search_terms: list[str] = []
        if metric_name:
            search_terms.append(metric_name)
        if service_name:
            search_terms.append(service_name)
        search_terms.extend(error_patterns[:3])

        for term in search_terms:
            try:
                items = await self.search_code(term, max_results=3)
            except Exception:
                logger.warning("GitHub search failed for term: %s", term, exc_info=True)
                continue

            for item in items:
                full_name = item["repository"]["full_name"]
                path = item["path"]
                key = f"{full_name}/{path}"
                if key in seen_paths:
                    continue
                seen_paths.add(key)

                try:
                    content = await self.get_file_content(
                        owner=item["repository"]["owner"]["login"],
                        repo=item["repository"]["name"],
                        path=path,
                    )
                    lines = content.splitlines()
                    snippet = "\n".join(lines[:60])
                except Exception:
                    logger.warning("Failed to fetch content for %s", key, exc_info=True)
                    snippet = "(content unavailable)"

                references.append(
                    CodeReference(
                        repo=full_name,
                        file_path=path,
                        snippet=snippet,
                        github_link=item.get("html_url", ""),
                    )
                )

        return references
