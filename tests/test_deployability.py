"""Guards against the class of bug that only appears once deployed.

The first Streamlit Cloud deploy died with ModuleNotFoundError: No module named
'medlog'. Locally `pip install -e .` had masked it; the host installs
requirements.txt and nothing else. These tests assert the properties that make
the repo runnable on a host that never installs the project itself.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ui_common_puts_repo_root_on_path_before_importing_medlog():
    """Streamlit runs ui/app.py as a script, so only ui/ lands on sys.path."""
    src = (ROOT / "ui" / "common.py").read_text()
    shim = src.index("sys.path.insert(0, _ROOT)")
    # No medlog import may appear at module level before the shim.
    assert "from medlog" not in src[:shim], "medlog imported before the path shim"
    assert "import medlog" not in src[:shim]


def test_every_ui_entrypoint_imports_common_before_medlog():
    """The shim only helps if `common` is imported first everywhere."""
    for f in [ROOT / "ui" / "app.py", *sorted((ROOT / "ui" / "pages").glob("*.py"))]:
        src = f.read_text()
        if "medlog" not in src:
            continue
        common_at = src.index("from common import")
        first_medlog = min(
            (src.index(t) for t in ("from medlog", "import medlog") if t in src),
            default=len(src),
        )
        assert common_at < first_medlog, f"{f.name} imports medlog before common"


def test_requirements_covers_every_third_party_import():
    """requirements.txt is what the host installs; pyproject is not consulted."""
    req = (ROOT / "requirements.txt").read_text().lower()
    for pkg in ["mem0ai", "anthropic", "fastapi", "streamlit", "pydantic",
                "httpx", "pyyaml", "pandas", "altair", "markdown-it-py",
                "python-dotenv", "pydantic-settings"]:
        assert pkg in req, f"{pkg} missing from requirements.txt"


def test_demo_cache_is_committed_and_complete():
    """A deploy with only MEM0_API_KEY depends on every artifact being present."""
    from medlog import demo
    assert not demo.missing(), f"demo_cache incomplete: {demo.missing()}"


def test_fixtures_are_committed_for_cold_boot():
    """medlog.db is gitignored, so a fresh instance rebuilds SQLite from these."""
    for name in ("maya", "arjun", "rosa"):
        assert (ROOT / "evals" / "fixtures" / f"{name}.yaml").exists()


def test_no_secrets_tracked_by_git():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                         text=True).stdout.split()
    assert ".env" not in out, ".env is tracked -- it holds a real API key"
    assert not [f for f in out if f.endswith(".db")]
