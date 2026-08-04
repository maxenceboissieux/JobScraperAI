from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_failed_e2e_run_preserves_and_reports_workspace_artifacts() -> None:
    runner = (PROJECT_ROOT / "scripts" / "run-e2e.sh").read_text(encoding="utf-8")

    assert 'JOBSCRAPER_E2E_ARTIFACTS="$PROJECT_ROOT/.artifacts/playwright"' in runner
    assert 'if [ "$cleanup_status" -ne 0 ]' in runner
    assert "Artefacts Playwright conservés" in runner
    assert 'rm -rf "$JOBSCRAPER_E2E_ARTIFACTS"' not in runner
