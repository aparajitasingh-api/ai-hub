from pydantic import BaseModel


class CodeReference(BaseModel):
    repo: str
    file_path: str
    line_start: int | None = None
    line_end: int | None = None
    snippet: str
    github_link: str


class RCAAnalysis(BaseModel):
    alert_id: str
    probable_cause: str
    confidence: str  # "high", "medium", "low"
    evidence: list[str]
    code_references: list[CodeReference]
    suggested_actions: list[str]
    rendered_text: str = ""
