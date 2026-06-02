"""Adapter for CXAS Versions and Deployments REST API.

Wraps ces.googleapis.com/v1alpha1 Versions/Deployments endpoints.
Falls back to no-op when google-auth is unavailable.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

_ENDPOINT = "https://ces.googleapis.com/v1alpha1"


class CXASVersionsAdapter:
    """Thin wrapper for CXAS Versions and Deployments management."""

    def __init__(self, *, full_app_name: str) -> None:
        """
        Args:
            full_app_name: Fully-qualified CXAS app resource name:
                ``projects/{project}/locations/{location}/apps/{app}``
        """
        self._app = full_app_name
        self._session = self._build_session()

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        return self._session is not None

    def _build_session(self):
        try:
            import google.auth
            import google.auth.transport.requests
            creds, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            return google.auth.transport.requests.AuthorizedSession(creds)
        except Exception as exc:
            log.warning("CXASVersionsAdapter: auth unavailable: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Versions
    # ------------------------------------------------------------------

    def list_versions(self, page_size: int = 20) -> list[dict[str, Any]]:
        """Return up to `page_size` versions for the app, newest first."""
        if not self._session:
            return []
        url = (
            f"{_ENDPOINT}/{self._app}/versions"
            f"?pageSize={page_size}&orderBy=createTime+desc"
        )
        try:
            resp = self._session.get(url, timeout=30)
            resp.raise_for_status()
            return resp.json().get("agentVersions", [])
        except Exception as exc:
            log.error("list_versions failed: %s", exc)
            return []

    def create_version(
        self, display_name: str, description: str = ""
    ) -> dict[str, Any]:
        """Snapshot the current agent state as a new immutable version."""
        if not self._session:
            return {}
        url = f"{_ENDPOINT}/{self._app}/versions"
        body: dict[str, Any] = {"displayName": display_name}
        if description:
            body["description"] = description
        try:
            resp = self._session.post(url, json=body, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            log.info("Created version: %s", data.get("name"))
            return data
        except Exception as exc:
            log.error("create_version failed: %s", exc)
            return {}

    def get_version(self, version_id: str) -> dict[str, Any]:
        if not self._session:
            return {}
        url = f"{_ENDPOINT}/{self._app}/versions/{version_id}"
        try:
            resp = self._session.get(url, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            log.error("get_version failed: %s", exc)
            return {}

    def delete_version(self, version_id: str) -> bool:
        """Delete a non-deployed version. Returns True on success."""
        if not self._session:
            return False
        url = f"{_ENDPOINT}/{self._app}/versions/{version_id}"
        try:
            resp = self._session.delete(url, timeout=30)
            resp.raise_for_status()
            return True
        except Exception as exc:
            log.error("delete_version failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Deployments
    # ------------------------------------------------------------------

    def list_deployments(self) -> list[dict[str, Any]]:
        """Return current deployment state across all environments."""
        if not self._session:
            return []
        url = f"{_ENDPOINT}/{self._app}/deployments"
        try:
            resp = self._session.get(url, timeout=30)
            resp.raise_for_status()
            return resp.json().get("agentDeployments", [])
        except Exception as exc:
            log.error("list_deployments failed: %s", exc)
            return []

    def deploy_version(
        self,
        version_id: str,
        *,
        traffic_split: int = 100,
        environment: str = "live",
    ) -> dict[str, Any]:
        """Route traffic to a specific version.

        Args:
            version_id: Version short-ID or full resource name.
            traffic_split: Percentage of traffic to route (1-100).
            environment: CXAS deployment environment (e.g. ``live``, ``test``).
        """
        if not self._session:
            return {}
        url = f"{_ENDPOINT}/{self._app}/deployments/{environment}"
        version_name = (
            version_id
            if version_id.startswith("projects/")
            else f"{self._app}/versions/{version_id}"
        )
        body = {
            "agentVersion": version_name,
            "trafficSplit": {"live": traffic_split},
        }
        try:
            resp = self._session.patch(url, json=body, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            log.info(
                "Deployed version %s to %s (%s%%)",
                version_id, environment, traffic_split,
            )
            return data
        except Exception as exc:
            log.error("deploy_version failed: %s", exc)
            return {}

    def get_active_version(self) -> str:
        """Return the version ID currently receiving 100% live traffic, or ''."""
        for dep in self.list_deployments():
            if dep.get("trafficSplit", {}).get("live", 0) == 100:
                v = dep.get("agentVersion", "")
                return v.split("/")[-1] if v else ""
        return ""
