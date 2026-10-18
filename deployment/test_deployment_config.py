#!/usr/bin/env python3
"""
Unit tests for deployment packaging, resource limits, and healthcheck.
"""

import os
import subprocess
import sys
import yaml
from pathlib import Path

DEPLOYMENT_DIR = Path(__file__).resolve().parent
COMPOSE_FILE = DEPLOYMENT_DIR / "docker-compose.yml"
DOCKERFILE = DEPLOYMENT_DIR / "Dockerfile"
HEALTHCHECK_FILE = DEPLOYMENT_DIR / "healthcheck.py"
ENTRYPOINT_FILE = DEPLOYMENT_DIR / "entrypoint.sh"


def test_docker_compose_syntax_and_guards():
    """Verify docker-compose.yml structure, memory hard limit, cpus, logging, and healthcheck."""
    assert COMPOSE_FILE.exists(), "docker-compose.yml must exist"

    with open(COMPOSE_FILE, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    services = config.get("services", {})
    assert "alpaca-trader" in services, "Service 'alpaca-trader' must be defined"
    svc = services["alpaca-trader"]

    # 1. Memory hard limit verification (180MB)
    assert svc.get("mem_limit") == "180m", f"Expected mem_limit: 180m, got {svc.get('mem_limit')}"
    deploy_limits = svc.get("deploy", {}).get("resources", {}).get("limits", {})
    assert deploy_limits.get("memory") == "180M", f"Expected deploy limit memory: 180M, got {deploy_limits.get('memory')}"

    # 2. CPU limit verification (0.75)
    assert float(svc.get("cpus", 0)) == 0.75, f"Expected cpus: 0.75, got {svc.get('cpus')}"
    assert float(deploy_limits.get("cpus", 0)) == 0.75, f"Expected deploy cpus: 0.75, got {deploy_limits.get('cpus')}"

    # 3. Restart policy
    assert svc.get("restart") == "unless-stopped", f"Expected restart: unless-stopped, got {svc.get('restart')}"

    # 4. Healthcheck
    hc = svc.get("healthcheck", {})
    assert "test" in hc, "healthcheck must define test command"
    assert "healthcheck.py" in " ".join(hc["test"]) if isinstance(hc["test"], list) else hc["test"]
    assert hc.get("interval") == "30s"
    assert hc.get("retries") == 3

    # 5. Log rotation (protecting VPS disk)
    logging_cfg = svc.get("logging", {})
    assert logging_cfg.get("driver") == "json-file"
    opts = logging_cfg.get("options", {})
    assert opts.get("max-size") == "10m"
    assert opts.get("max-file") == "3"

    print("✓ docker-compose.yml resource guards & policies verified successfully")


def test_dockerfile_contents():
    """Verify Dockerfile optimization flags, security, and instructions."""
    assert DOCKERFILE.exists(), "Dockerfile must exist"
    content = DOCKERFILE.read_text(encoding="utf-8")

    assert "MALLOC_ARENA_MAX=2" in content, "Dockerfile must set MALLOC_ARENA_MAX=2"
    assert "PYTHONUNBUFFERED=1" in content, "Dockerfile must set PYTHONUNBUFFERED=1"
    assert "PYTHONDONTWRITEBYTECODE=1" in content, "Dockerfile must set PYTHONDONTWRITEBYTECODE=1"
    assert "useradd" in content or "adduser" in content, "Dockerfile must create non-root user"
    assert "HEALTHCHECK" in content, "Dockerfile must declare HEALTHCHECK"
    assert "ENTRYPOINT" in content, "Dockerfile must declare ENTRYPOINT"

    print("✓ Dockerfile optimization and security verified successfully")


def test_entrypoint_syntax():
    """Verify bash syntax of entrypoint.sh."""
    assert ENTRYPOINT_FILE.exists(), "entrypoint.sh must exist"
    result = subprocess.run(["bash", "-n", str(ENTRYPOINT_FILE)], capture_output=True, text=True)
    assert result.returncode == 0, f"entrypoint.sh bash syntax error: {result.stderr}"
    print("✓ entrypoint.sh bash syntax check passed")


def test_healthcheck_execution():
    """Execute healthcheck script in test mode."""
    assert HEALTHCHECK_FILE.exists(), "healthcheck.py must exist"
    # Run with HEALTHCHECK_SKIP_NETWORK=1 to test local memory verification logic
    env = os.environ.copy()
    env["HEALTHCHECK_SKIP_NETWORK"] = "1"
    result = subprocess.run(
        [sys.executable, str(HEALTHCHECK_FILE)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"healthcheck.py failed: stdout={result.stdout}, stderr={result.stderr}"
    assert "HEALTHCHECK OK" in result.stdout
    print("✓ healthcheck.py execution passed")


if __name__ == "__main__":
    test_docker_compose_syntax_and_guards()
    test_dockerfile_contents()
    test_entrypoint_syntax()
    test_healthcheck_execution()
    print("\nAll deployment verification tests passed!")
