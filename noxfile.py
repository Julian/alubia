from pathlib import Path
from tempfile import TemporaryDirectory
import os

import nox

ROOT = Path(__file__).parent
PYPROJECT = ROOT / "pyproject.toml"
DOCS = ROOT / "docs"

PACKAGE = ROOT / "alubia"


SUPPORTED = ["3.14"]
LATEST = SUPPORTED[-1]

nox.options.default_venv_backend = "uv"
nox.options.sessions = []


def session(default=True, python=LATEST, **kwargs):  # noqa: D103
    def _session(fn):
        if default:
            nox.options.sessions.append(kwargs.get("name", fn.__name__))
        return nox.session(python=python, **kwargs)(fn)

    return _session


@session(python=SUPPORTED)
def tests(session):
    """
    Run the test suite.
    """
    session.run_install(
        "uv",
        "sync",
        "--group=test",
        f"--python={session.virtualenv.location}",
        env={"UV_PROJECT_ENVIRONMENT": session.virtualenv.location},
    )

    if session.posargs and session.posargs[0] == "coverage":
        if len(session.posargs) > 1 and session.posargs[1] == "github":
            github = Path(os.environ["GITHUB_STEP_SUMMARY"])
        else:
            github = None

        session.install("coverage[toml]")
        session.run("coverage", "run", "-m", "pytest", PACKAGE)
        if github is None:
            session.run("coverage", "report")
        else:
            with github.open("a") as summary:
                summary.write("### Coverage\n\n")
                summary.flush()  # without a flush, output seems out of order.
                session.run(
                    "coverage",
                    "report",
                    "--format=markdown",
                    stdout=summary,
                )
    else:
        session.run("python", "-m", "pytest", *session.posargs, PACKAGE)


@session(tags=["build"])
def build(session):
    """
    Build a distribution suitable for PyPI and check its validity.
    """
    session.install("build[uv]", "twine")
    with TemporaryDirectory() as tmpdir:
        session.run(
            "pyproject-build",
            "--installer=uv",
            ROOT,
            "--outdir",
            tmpdir,
        )
        session.run("twine", "check", "--strict", tmpdir + "/*")


@session()
def secrets(session):
    """
    Check for accidentally included secrets.
    """
    session.install("detect-secrets")
    session.run("detect-secrets", "scan", ROOT)


@session(tags=["style"])
def style(session):
    """
    Check for coding style.
    """
    session.install("ruff")
    session.run("ruff", "check", ROOT, __file__)


@session()
def typing(session):
    """
    Statically check typing annotations.
    """
    session.run_install(
        "uv",
        "sync",
        "--extra=pdf",
        "--group=typing",
        f"--python={session.virtualenv.location}",
        env={"UV_PROJECT_ENVIRONMENT": session.virtualenv.location},
    )
    session.run("ty", "check", *session.posargs, PACKAGE)
