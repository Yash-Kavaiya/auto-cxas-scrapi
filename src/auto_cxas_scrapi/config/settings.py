from __future__ import annotations
from pathlib import Path
from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8",
        case_sensitive=False, extra="ignore",
    )
    env: str = Field(default="development", alias="AUTO_CXAS_ENV")
    google_cloud_project: str = Field(default="", alias="GOOGLE_CLOUD_PROJECT")
    google_cloud_location: str = Field(default="global", alias="GOOGLE_CLOUD_LOCATION")
    app_name: str = Field(default="", alias="AUTO_CXAS_APP_NAME")
    agent_name: str = Field(default="", alias="AUTO_CXAS_AGENT_NAME")
    runs_dir: Path = Field(default=Path(".auto-cxas/runs"), alias="AUTO_CXAS_RUNS_DIR")
    state_dir: Path = Field(default=Path(".auto-cxas/state"), alias="AUTO_CXAS_STATE_DIR")
    log_level: str = Field(default="INFO", alias="AUTO_CXAS_LOG_LEVEL")
    llm_provider: Literal["gemini", "openai", "anthropic"] = Field(
        default="gemini", alias="AUTO_CXAS_LLM_PROVIDER"
    )
    llm_model: str = Field(default="", alias="AUTO_CXAS_LLM_MODEL")
    approval_mode: Literal["manual", "auto"] = Field(
        default="manual", alias="AUTO_CXAS_APPROVAL_MODE"
    )
    min_score_delta: float = Field(default=0.01, alias="AUTO_CXAS_MIN_SCORE_DELTA")
    max_experiments_per_loop: int = Field(default=1000, alias="AUTO_CXAS_MAX_EXPERIMENTS_PER_LOOP")
    max_parallel_evals: int = Field(default=3, alias="AUTO_CXAS_MAX_PARALLEL_EVALS")
    eval_timeout_seconds: int = Field(default=180, alias="AUTO_CXAS_EVAL_TIMEOUT_SECONDS")
    baseline_cache_ttl_seconds: int = Field(
        default=300, alias="AUTO_CXAS_BASELINE_CACHE_TTL_SECONDS"
    )
    # Convergence detection (autoresearch-inspired)
    convergence_window: int = Field(default=10, alias="AUTO_CXAS_CONVERGENCE_WINDOW")
    convergence_threshold: float = Field(default=0.002, alias="AUTO_CXAS_CONVERGENCE_THRESHOLD")
    # Callback server
    callback_server_url: str = Field(default="", alias="AUTO_CXAS_CALLBACK_SERVER_URL")
    callback_secret: str = Field(default="", alias="AUTO_CXAS_CALLBACK_SECRET")
    # Reporting
    generate_html_report: bool = Field(default=False, alias="AUTO_CXAS_GENERATE_HTML_REPORT")
    report_dir: Path = Field(default=Path(".auto-cxas/reports"), alias="AUTO_CXAS_REPORT_DIR")

    def ensure_directories(self) -> None:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        if self.generate_html_report:
            self.report_dir.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    s = Settings()
    s.ensure_directories()
    return s
