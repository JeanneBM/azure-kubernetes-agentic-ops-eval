from __future__ import annotations

import os
import json
import re

import httpx
from azure.identity import DefaultAzureCredential

from .telemetry import tool

from .contracts import Evidence, Facts
from .safety import ImageRef, PolicyViolation, parse_image, edit_distance

_MANIFEST_TYPES = ", ".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)


class RegistryError(Exception):
    """The registry could not give a definite answer (auth, network, unexpected status)."""


class RegistryEvidenceProvider:
    """Enrich cluster facts with an authenticated, read-only manifest check.

    This checks the failing image, never a model-supplied URL or an Event string.
    Diagnostic access does not establish kubelet access or authorize a repair.
    """

    def __init__(self, evidence_provider, registry, *, namespace, allowed_registries):
        self._evidence = evidence_provider
        self._registry = registry
        self._namespace = namespace
        self._allowed = frozenset(r.strip().lower() for r in allowed_registries if r.strip())

    def collect(self, trigger):
        if trigger.namespace != self._namespace:
            raise PolicyViolation("Registry evidence requested outside managed namespace")
        raw = self._evidence.collect(trigger)
        # Multiple failing containers remain ambiguous; do not select one.
        if len(raw.pull_failures) != 1:
            return raw
        failure = raw.pull_failures[0]
        image = parse_image(failure.image)
        if image.registry not in self._allowed:
            raise PolicyViolation("Registry evidence requested outside allowed registries")
        try:
            status = "exists" if self._registry.exists(image) else "missing"
        except RegistryError:
            status = "unknown"
        candidates = ()
        candidate_status = "not_checked"
        if status == "missing":
            try:
                candidates = self._registry.candidates(image)
                candidate_status = "complete"
            except RegistryError:
                candidate_status = "unknown"
        item = Evidence(
            "authenticated-registry-manifest",
            json.dumps({"container": failure.container, "image": str(image),
                        "status": status, "identity": "diagnostic",
                        "candidate_status": candidate_status,
                        "verified_candidates": [str(candidate) for candidate in candidates],
                        "kubelet_access": "not_verified"}),
            f"acr://{image.registry}/{image.repository}:{image.tag}",
        )
        return Facts(raw.items + (item,), raw.groundedness, raw.safe_action,
                     raw.summary, raw.pull_failures)


class AcrRegistry:
    """Checks whether an image tag exists in Azure Container Registry.

    Uses the workload identity of the pod: AAD token -> ACR refresh token ->
    repository-scoped pull token -> manifest lookup. The identity needs the
    AcrPull role on the registry. Only 200 (exists) and 404 (missing) are
    treated as answers; everything else raises so the incident is escalated.
    """

    def __init__(self, *, credential=None, http_client: httpx.Client | None = None) -> None:
        self._credential = credential or DefaultAzureCredential()
        self._client = http_client or httpx.Client(timeout=20)

    def exists(self, image: ImageRef) -> bool:
        tool('acr_check', {'image': str(image)})
        token = self._pull_token(image)
        try:
            response = self._client.head(
                f"https://{image.registry}/v2/{image.repository}/manifests/{image.tag}",
                headers={"Authorization": f"Bearer {token}", "Accept": _MANIFEST_TYPES},
            )
        except httpx.HTTPError as error:
            raise RegistryError(f"Registry request failed: {error}") from error
        if response.status_code == 200:
            return True
        if response.status_code == 404:
            return False
        raise RegistryError(f"Unexpected registry status {response.status_code} for {image}")

    def _pull_token(self, image: ImageRef) -> str:
        return self._access_token(image.registry, f"repository:{image.repository}:pull")

    def candidates(self, image: ImageRef) -> tuple[ImageRef, ...]:
        """Verify close repository spellings at the unchanged tag.

        An incomplete or failed inventory must not appear to be a unique match.
        Bounds intentionally limit this discovery to small lab registries.
        """
        tool('acr_candidates', {'image': str(image)})
        token = self._access_token(image.registry, "registry:catalog:*")
        try:
            response = self._client.get(
                f"https://{image.registry}/v2/_catalog", params={"n": 100},
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            data = response.json()
            repositories = data["repositories"]
            if (not isinstance(repositories, list) or len(repositories) >= 100
                    or response.headers.get("Link") or data.get("link")):
                raise RegistryError("Registry inventory incomplete or outside discovery bounds")
            if any(not isinstance(repo, str) or len(repo) > 256 or not re.fullmatch(
                    r"[a-z0-9]+(?:(?:[._-]|__)[a-z0-9]+)*(?:/[a-z0-9]+(?:(?:[._-]|__)[a-z0-9]+)*)*",
                    repo) for repo in repositories):
                raise RegistryError("Invalid repository inventory")
            nearby = sorted({repo for repo in repositories
                             if repo != image.repository
                             and abs(len(repo) - len(image.repository)) <= 2
                             and edit_distance(image.repository, repo) <= 2})
            if len(nearby) > 10:
                raise RegistryError("Too many nearby repositories for bounded discovery")
            candidates = [ImageRef(image.registry, repo, image.tag) for repo in nearby]
            return tuple(candidate for candidate in candidates if self.exists(candidate))
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as error:
            raise RegistryError("Registry candidate discovery failed") from error

    def _access_token(self, registry: str, scope: str) -> str:
        aad_token = self._credential.get_token("https://management.azure.com/.default").token
        exchange = {
            "grant_type": "access_token",
            "service": registry,
            "access_token": aad_token,
        }
        tenant = os.environ.get("AZURE_TENANT_ID")
        if tenant:
            exchange["tenant"] = tenant
        try:
            refresh = self._client.post(f"https://{registry}/oauth2/exchange", data=exchange)
            refresh.raise_for_status()
            access = self._client.post(
                f"https://{registry}/oauth2/token",
                data={
                    "grant_type": "refresh_token",
                    "service": registry,
                    "scope": scope,
                    "refresh_token": refresh.json()["refresh_token"],
                },
            )
            access.raise_for_status()
            return access.json()["access_token"]
        except (httpx.HTTPError, KeyError, ValueError) as error:
            raise RegistryError(f"Could not obtain a registry token: {error}") from error
