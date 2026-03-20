from unittest.mock import AsyncMock

import pytest

from src.models.rca import CodeReference
from src.services.rca_agent import RCAAgent


@pytest.fixture
def mock_github():
    return AsyncMock()


@pytest.fixture
def rca_agent(mock_github):
    return RCAAgent(github_client=mock_github)


@pytest.mark.asyncio
async def test_analyze_with_matching_code(rca_agent, mock_github, sample_report):
    mock_github.find_relevant_code.return_value = [
        CodeReference(
            repo="myorg/payment-api",
            file_path="src/handlers/payment.py",
            snippet="def process_payment():\n    # Connection pool exhausted handling\n    raise ConnectionError('pool exhausted')",
            github_link="https://github.com/myorg/payment-api/blob/main/src/handlers/payment.py",
        )
    ]

    result = await rca_agent.analyze(sample_report)

    assert result.alert_id == "12345678"
    assert result.confidence in ("low", "medium", "high")
    assert result.rendered_text != ""
    assert "ROOT CAUSE ANALYSIS" in result.rendered_text
    mock_github.find_relevant_code.assert_called_once()


@pytest.mark.asyncio
async def test_analyze_no_code_found(rca_agent, mock_github, sample_report):
    mock_github.find_relevant_code.return_value = []

    result = await rca_agent.analyze(sample_report)

    assert result.confidence == "low"
    assert len(result.code_references) == 0
    assert "manual investigation" in result.probable_cause.lower() or "could not determine" in result.probable_cause.lower()


@pytest.mark.asyncio
async def test_analyze_github_failure(rca_agent, mock_github, sample_report):
    mock_github.find_relevant_code.side_effect = RuntimeError("GitHub API down")

    result = await rca_agent.analyze(sample_report)

    # Should handle gracefully, not crash
    assert result.confidence == "low"
    assert len(result.code_references) == 0
