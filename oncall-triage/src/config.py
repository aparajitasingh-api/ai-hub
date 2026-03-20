from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatadogSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DD_")

    api_key: str = ""
    app_key: str = ""
    site: str = "datadoghq.com"

    @property
    def base_url(self) -> str:
        return f"https://api.{self.site}"


class ElasticsearchSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ES_")

    hosts: str = "http://localhost:9200"
    api_key: str = ""
    username: str = ""
    password: str = ""
    index_pattern: str = "app-logs-*"
    kibana_base_url: str = "http://localhost:5601"

    @property
    def hosts_list(self) -> list[str]:
        return [h.strip() for h in self.hosts.split(",") if h.strip()]


class GoogleChatSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GCHAT_")

    webhook_url: str = ""


class GitHubSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GITHUB_")

    token: str = ""
    org: str = ""
    default_repos: str = ""

    @property
    def repos_list(self) -> list[str]:
        return [r.strip() for r in self.default_repos.split(",") if r.strip()]


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    metric_window_minutes: int = 10
    max_log_results: int = 200

    datadog: DatadogSettings = Field(default_factory=DatadogSettings)
    elasticsearch: ElasticsearchSettings = Field(default_factory=ElasticsearchSettings)
    google_chat: GoogleChatSettings = Field(default_factory=GoogleChatSettings)
    github: GitHubSettings = Field(default_factory=GitHubSettings)
