#!/usr/bin/env python3
"""Inspect and deploy the paper dashboard through GitHub's supported REST API.

Default invocation is read-only. Mutations require an explicit subcommand.
Authentication is used only in HTTPS headers and is never printed or persisted.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class GitHubError(RuntimeError):
    def __init__(self, status: int | None, message: str):
        self.status = status
        super().__init__(message)


class GitHub:
    def __init__(self, repository: str, token: str):
        parts = repository.split("/")
        if len(parts) != 2 or not all(parts) or any(
            not all(c.isalnum() or c in "-_." for c in part) for part in parts
        ):
            raise ValueError("repository must be an owner/name identifier")
        if not token:
            raise ValueError("GH_TOKEN or GITHUB_TOKEN must be bound in environment settings")
        self.repository = repository
        self._token = token
        self.base = "https://api.github.com/repos/" + repository

    def request(self, path: str, method: str = "GET", payload: Any = None) -> Any:
        if (path and not path.startswith("/")) or "://" in path:
            raise ValueError("Only repository-relative GitHub API paths are supported")
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base + path,
            data=body,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": "Bearer " + self._token,
                "User-Agent": "TradingAgent-deployment",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
                return json.loads(raw) if raw else {"status": response.status}
        except urllib.error.HTTPError as exc:
            try:
                value = json.loads(exc.read())
                message = str(value.get("message", "GitHub API request failed"))
            except (ValueError, OSError):
                message = "GitHub API request failed"
            message = message.replace(self._token, "[redacted]")
            raise GitHubError(exc.code, f"GitHub API HTTP {exc.code}: {message}") from None
        except urllib.error.URLError:
            raise GitHubError(None, "GitHub API unreachable; check approved network access") from None

    def status(self) -> dict[str, Any]:
        repo = self.request("")
        result = {
            "repository": repo["full_name"],
            "private": repo["private"],
            "default_branch": repo["default_branch"],
            "permissions": repo.get("permissions", {}),
        }
        for label, path in (
            ("pages", "/pages"),
            ("actions_settings", "/actions/permissions"),
            ("workflow_permissions", "/actions/permissions/workflow"),
            ("workflows", "/actions/workflows"),
        ):
            try:
                value = self.request(path)
                if label == "pages":
                    value = {key: value.get(key) for key in ("status", "html_url", "build_type", "source")}
                elif label == "workflows":
                    value = {"total_count": value["total_count"], "workflows": [
                        {key: row.get(key) for key in ("id", "name", "path", "state")}
                        for row in value.get("workflows", [])
                    ]}
                result[label] = value
            except GitHubError as exc:
                result[label] = {"available": False, "http_status": exc.status, "message": str(exc)}
        return result

    def enable_pages(self) -> Any:
        """Create/adjust Pages without changing repository visibility."""
        try:
            self.request("/pages")
        except GitHubError as exc:
            if exc.status != 404:
                raise
            return self.request("/pages", "POST", {"build_type": "workflow"})
        return self.request("/pages", "PUT", {"build_type": "workflow"})

    def dispatch(self, workflow: str, ref: str) -> Any:
        identifier = urllib.parse.quote(workflow, safe="")
        return self.request(f"/actions/workflows/{identifier}/dispatches", "POST", {"ref": ref})

    def wait_run(self, workflow: str, commit: str | None, timeout: int) -> dict[str, Any]:
        identifier = urllib.parse.quote(workflow, safe="")
        deadline = time.monotonic() + timeout
        while True:
            query = "?per_page=10"
            if commit:
                query += "&head_sha=" + urllib.parse.quote(commit, safe="")
            data = self.request(f"/actions/workflows/{identifier}/runs{query}")
            candidates = data.get("workflow_runs", [])
            if candidates:
                run = candidates[0]
                output = {key: run.get(key) for key in
                          ("id", "html_url", "status", "conclusion", "head_sha", "created_at")}
                if run["status"] == "completed":
                    return output
            if time.monotonic() >= deadline:
                return {"status": "timeout", "message": "No completed matching workflow run observed"}
            time.sleep(min(10, max(0, deadline - time.monotonic())))

    def verified_url(self, deployed_url: str | None = None) -> dict[str, Any]:
        """Return only a Pages URL reported by GitHub and verified reachable."""
        url = deployed_url
        if not url:
            pages = self.request("/pages")
            url = pages.get("html_url")
        parsed = urllib.parse.urlparse(url or "")
        if parsed.scheme != "https" or not parsed.hostname:
            raise GitHubError(None, "GitHub has not reported an HTTPS Pages URL")
        try:
            with urllib.request.urlopen(urllib.request.Request(
                url, headers={"User-Agent": "TradingAgent-verification"}
            ), timeout=30) as response:
                body = response.read(65536)
                if response.status != 200 or b"TradingAgent" not in body:
                    raise GitHubError(response.status, "Page did not return the expected TradingAgent dashboard")
                return {"url": response.url, "http_status": response.status, "verified": True}
        except urllib.error.HTTPError as exc:
            raise GitHubError(exc.code, f"Dashboard verification returned HTTP {exc.code}") from None
        except urllib.error.URLError:
            raise GitHubError(None, "Reported dashboard URL is unreachable from this environment") from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "enable-pages", "dispatch", "wait", "verify"), nargs="?", default="status")
    parser.add_argument("--repository", default="lijingchiu/TradingAgent")
    parser.add_argument("--workflow", default="paper-trader.yml")
    parser.add_argument("--ref", default="main")
    parser.add_argument("--commit", help="Match workflow runs to this commit SHA")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--token-env", help="Use this existing environment binding name, never a token value")
    parser.add_argument("--url", help="Exact HTTPS URL observed in a completed deployment output (verify only)")
    args = parser.parse_args()
    try:
        token = os.environ.get(args.token_env, "") if args.token_env else (
            (os.environ.get("PAGES_ADMIN_TOKEN") if args.command in ("enable-pages", "verify") else None)
            or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
        )
        api = GitHub(args.repository, token)
        if args.command == "status":
            result = api.status()
        elif args.command == "enable-pages":
            result = api.enable_pages()
        elif args.command == "dispatch":
            result = api.dispatch(args.workflow, args.ref)
        elif args.command == "wait":
            result = api.wait_run(args.workflow, args.commit, max(0, args.timeout))
        else:
            result = api.verified_url(args.url)
        print(json.dumps(result, indent=2))
        if args.command == "wait" and result.get("conclusion") != "success":
            return 1
        return 0
    except (GitHubError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
