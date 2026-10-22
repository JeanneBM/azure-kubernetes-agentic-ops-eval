"""Create anonymized evidence archives without modifying raw evidence.

Unsupported binary content aborts packaging. Nested ZIPs are unpacked in memory,
sanitized with the same mapping, and rebuilt; they are never copied through blindly.
"""
from __future__ import annotations
import argparse
import io
import ipaddress
import json
from pathlib import Path
import re
import zipfile

UUID = re.compile(r"(?i)\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b")
EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}")
HOST = re.compile(r"(?i)\b[a-z0-9.-]+\.(?:azurecr\.io|openai\.azure\.com|azmk8s\.io|prod-aks\.azure\.com|blob\.core\.windows\.net|vault\.azure\.net)\b")
IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
JWT = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+")
PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.S)
USER_PATH = re.compile(r"(?i)(/home/|/Users/|[A-Z]:\\Users\\)([^/\\\s\"']+)")
RESOURCE_NAME = re.compile(r"(?i)/(?:resourceGroups|registries|accounts|managedClusters|userAssignedIdentities|networkWatchers)/([^/\s\"'?#]+)")
SECRET_KEYS = {
    "password", "passwd", "clientsecret", "client_secret", "apikey", "api_key",
    "access_token", "accesstoken", "refresh_token", "refreshtoken",
    "authorization", "x-agent-token", "x-webhook-token", "token",
    "client-key-data", "client-certificate-data", "certificate-authority-data",
}
SECRET_ENV = re.compile(r"(?i)(?:TOKEN|PASSWORD|SECRET|API_KEY|APIKEY|CONNECTION_STRING)")
SECRET_FIELD = re.compile(
    r"(?i)(?:api[_-]?key|client[_-]?secret|access[_-]?token|refresh[_-]?token|"
    r"password|passwd|authorization|token|secret|connection[_-]?string)$"
)
SECRET_ASSIGNMENT = re.compile(
    r"""(?ix)
    (?P<prefix>
      (?<![\w-])
      (?:[a-z0-9_-]*?(?:api[_-]?key|client[_-]?secret|access[_-]?token|
         refresh[_-]?token|password|passwd|authorization|token|secret|connection[_-]?string))
      (?:\\?["'])? \s* [=:] \s*
    )
    (?:
      (?P<quote>\\?["']) (?P<quoted>.*?) (?P=quote)
      | (?P<bare>[^\s"',{}\[\]\\]+)
    )
    """
)

def redact_assignment(match):
    quote = match.group("quote") or ""
    return match.group("prefix") + quote + "REDACTED_SECRET" + quote

def unredacted_assignment(value):
    for match in SECRET_ASSIGNMENT.finditer(value):
        captured = match.group("quoted") if match.group("quote") else match.group("bare")
        # SDK snapshots include optional metadata such as
        # automount_service_account_token: null/false. These JSON literals
        # are configuration, not credential contents. Quoted values still count.
        if not match.group("quote") and captured in ("null", "true", "false"):
            continue
        if captured and captured not in ("REDACTED_SECRET", "REDACTED_TOKEN"):
            return True
    return False

class Sanitizer:
    def __init__(self):
        self.mapping = {}
        self.counts = {}
        self.files = 0

    def alias(self, kind, value):
        key = (kind, value)
        if key not in self.mapping:
            self.counts[kind] = self.counts.get(kind, 0) + 1
            self.mapping[key] = f"ANON_{kind}_{self.counts[kind]:03d}"
        return self.mapping[key]

    def discover(self, text):
        for match in HOST.finditer(text):
            host = match.group()
            # Replace the resource prefix everywhere, including CLI commands.
            first = host.split(".")[0]
            if len(first) > 3:
                self.mapping.setdefault(("RESOURCE", first), self.alias("RESOURCE", first))
        for match in RESOURCE_NAME.finditer(text):
            self.alias("RESOURCE", match.group(1))
        try:
            value = json.loads(text)
        except ValueError:
            return
        self.discover_json(value)

    def discover_json(self, value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ("nodeName", "computerName", "createdBy", "lastModifiedBy", "principalName") and isinstance(item, str) and item:
                    self.alias("IDENTITY", item)
                if key in ("hostIP", "podIP", "ip") and isinstance(item, str):
                    try:
                        ipaddress.ip_address(item)
                        self.alias("IP", item)
                    except ValueError:
                        pass
                self.discover_json(item)
        elif isinstance(value, list):
            for item in value:
                self.discover_json(item)

    def text(self, value):
        value = PRIVATE_KEY.sub("REDACTED_PRIVATE_KEY", value)
        value = JWT.sub("REDACTED_TOKEN", value)
        value = re.sub(r"(?i)(Bearer\s+)[A-Za-z0-9_./+=-]{8,}", r"\1REDACTED_TOKEN", value)
        value = re.sub(r"(?i)([?&](?:sig|token|access_token|code)=)[^\s&\"']+", r"\1REDACTED_SECRET", value)
        value = SECRET_ASSIGNMENT.sub(redact_assignment, value)
        value = EMAIL.sub(lambda m: self.alias("EMAIL", m.group()), value)
        value = UUID.sub(lambda m: self.alias("UUID", m.group().lower()), value)
        value = USER_PATH.sub(lambda m: m.group(1) + "ANON_USER", value)
        # Identity/node names from JSON and resource names from Azure paths/hosts.
        for (kind, original), replacement in sorted(list(self.mapping.items()), key=lambda p: len(p[0][1]), reverse=True):
            if kind in ("RESOURCE", "IDENTITY", "IP"):
                value = value.replace(original, replacement)
        value = HOST.sub(lambda m: self.alias("HOST", m.group().lower()) + ".example.invalid", value)
        def ip_alias(match):
            try:
                ipaddress.ip_address(match.group())
            except ValueError:
                return match.group()
            return self.alias("IP", match.group())
        return IPV4.sub(ip_alias, value)

    def json_value(self, value):
        if isinstance(value, dict):
            output = {}
            is_secret = value.get("kind") == "Secret"
            for key, item in value.items():
                safe_key = self.text(key)
                if key.lower() in SECRET_KEYS or (is_secret and key in ("data", "stringData")):
                    output[safe_key] = "REDACTED_SECRET"
                elif key == "value" and SECRET_ENV.search(str(value.get("name", ""))):
                    output[safe_key] = "REDACTED_SECRET"
                elif SECRET_FIELD.search(key) and item is not None and not isinstance(item, (dict, list, bool)):
                    output[safe_key] = "REDACTED_SECRET"
                else:
                    output[safe_key] = self.json_value(item)
            return output
        if isinstance(value, list):
            return [self.json_value(item) for item in value]
        if isinstance(value, str):
            # Kubernetes annotations can contain a second, escaped JSON document.
            if value.lstrip().startswith(("{", "[")):
                try:
                    nested = json.loads(value)
                    return json.dumps(self.json_value(nested), ensure_ascii=False)
                except ValueError:
                    pass
            return self.text(value)
        return value

    def content(self, name, data):
        if name.lower().endswith(".zip"):
            return self.archive(data)
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ValueError(f"Unsupported binary evidence: {name}; archive was not created") from error
        if "\x00" in text:
            raise ValueError(f"Unsupported binary evidence: {name}; archive was not created")
        try:
            parsed = json.loads(text)
        except ValueError:
            result = self.text(text)
        else:
            result = json.dumps(self.json_value(parsed), ensure_ascii=False, indent=2) + "\n"
        # Post-check known secret/identifier patterns; fail closed on leftovers.
        if UUID.search(result) or EMAIL.search(result) or JWT.search(result) or PRIVATE_KEY.search(result) or unredacted_assignment(result):
            raise ValueError(f"Unredacted identifier or secret in {name}; archive was not created")
        self.files += 1
        return result.encode("utf-8")

    def entries(self, data):
        with zipfile.ZipFile(io.BytesIO(data)) as source:
            for info in source.infolist():
                if not info.is_dir():
                    yield info.filename, source.read(info)

    def discover_entries(self, entries):
        for name, data in entries:
            if name.lower().endswith(".zip"):
                self.discover_entries(list(self.entries(data)))
            else:
                try:
                    self.discover(data.decode("utf-8-sig"))
                except UnicodeDecodeError:
                    pass

    def archive(self, data):
        entries = list(self.entries(data))
        self.discover_entries(entries)
        result = io.BytesIO()
        with zipfile.ZipFile(result, "w", zipfile.ZIP_DEFLATED) as target:
            for name, content in entries:
                target.writestr(self.text(name), self.content(name, content))
        return result.getvalue()


def package(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_dir():
        raise ValueError("Evidence directory is missing")
    if destination == source or source in destination.parents:
        raise ValueError("ZIP must be outside its source directory")
    # Remove an old output first: a failed sanitization must not leave a stale ZIP.
    destination.unlink(missing_ok=True)
    entries = []
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ValueError("Symlink evidence is unsupported")
        if path.is_file():
            entries.append((path.relative_to(source).as_posix(), path.read_bytes()))
    sanitizer = Sanitizer()
    sanitizer.discover_entries(entries)
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", zipfile.ZIP_DEFLATED) as target:
        for name, data in entries:
            target.writestr(sanitizer.text(name), sanitizer.content(name, data))
        target.writestr("ANONYMIZATION.json", json.dumps({
            "schema": 1, "files_processed": sanitizer.files,
            "raw_evidence_modified": False,
            "mapping_included": False,
            "note": "Evidence anonymized before packaging.",
        }, indent=2))
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_bytes(result.getvalue())
    temporary.replace(destination)
    print(f"Anonymized archive created: {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--destination", required=True)
    args = parser.parse_args()
    package(args.source, args.destination)
