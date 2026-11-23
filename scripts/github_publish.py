"""Mint a repository-scoped GitHub App token and publish a validated tree."""

import base64
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

REPOSITORY = "isct-companion/Isct-Data"


def app_configured():
    return bool(os.getenv("ISCT_GITHUB_APP_ID") and os.getenv("ISCT_GITHUB_INSTALLATION_ID")
                and Path("/run/isct-github/private-key.pem").is_file())


def app_token():
    def encode(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=")

    app_id = os.environ["ISCT_GITHUB_APP_ID"]
    installation_id = os.environ["ISCT_GITHUB_INSTALLATION_ID"]
    if not app_id.isdecimal() or not installation_id.isdecimal():
        raise ValueError("GitHub App and installation IDs must be numeric")
    now = int(time.time())
    claims = json.dumps({"iat": now - 60, "exp": now + 480, "iss": app_id}).encode()
    payload = b".".join((encode(b'{"alg":"RS256","typ":"JWT"}'), encode(claims)))
    signature = subprocess.run(
        ["openssl", "dgst", "-sha256", "-sign", "/run/isct-github/private-key.pem"],
        input=payload, stdout=subprocess.PIPE, check=True, timeout=10,
    ).stdout
    jwt = b".".join((payload, encode(signature))).decode("ascii")
    return request(jwt, "POST", f"/app/installations/{installation_id}/access_tokens", {
        "repositories": ["Isct-Data"], "permissions": {"contents": "write"},
    })["token"]


def request(token, method, path, body=None):
    query = Request("https://api.github.com" + path, method=method,
                    data=json.dumps(body).encode() if body is not None else None,
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                             "Content-Type": "application/json", "User-Agent": "Isct-Data-NAS"})
    try:
        with urlopen(query, timeout=60) as response:
            return json.load(response)
    except HTTPError as error:
        raise ValueError(f"GitHub API {method} {path} failed with HTTP {error.code}") from None


def push_main(base, files, message, *, api=request):
    token = app_token()
    path = f"/repos/{REPOSITORY}/git"
    if api(token, "GET", f"{path}/ref/heads/main")["object"]["sha"] != base:
        raise ValueError("main advanced during validation; retry on the latest main")
    previous = api(token, "GET", f"{path}/commits/{base}")
    tree = api(token, "POST", f"{path}/trees", {
        "base_tree": previous["tree"]["sha"],
        "tree": [{"path": name, "mode": "100644", "type": "blob",
                  **({"content": content} if content is not None else {"sha": None})}
                 for name, content in sorted(files.items())],
    })
    commit = api(token, "POST", f"{path}/commits", {
        "message": message, "tree": tree["sha"], "parents": [base],
    })
    ref = api(token, "PATCH", f"{path}/refs/heads/main", {"sha": commit["sha"], "force": False})
    if ref["object"]["sha"] != commit["sha"]:
        raise ValueError("GitHub returned an unexpected main commit")
    return {"changed": True, "commit": commit["sha"], "files": sorted(files)}
