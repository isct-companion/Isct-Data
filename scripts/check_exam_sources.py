#!/usr/bin/env python3
"""Poll official pages/PDFs; compare bytes with the last validated source review."""
import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parent.parent
HOST = "www.titech.ac.jp"
STATE = "review/exam-source-state.json"


def allowed_url(url, hosts=(HOST,)):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in hosts or
            parsed.port not in (None, 443) or parsed.username or parsed.password):
        raise ValueError(f"source outside HTTPS allowlist: {url}")
    return url


class OfficialRedirects(HTTPRedirectHandler):
    def __init__(self, hosts=(HOST,)):
        super().__init__()
        self.hosts = hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        allowed_url(newurl, self.hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, hosts=(HOST,)):
    request = Request(allowed_url(url, hosts), headers={"User-Agent": "Isct-Data-exam-monitor/1.0"})
    with build_opener(OfficialRedirects(hosts)).open(request, timeout=45) as response:
        allowed_url(response.url, hosts)
        content = response.read(32 * 1024 * 1024 + 1)
        if len(content) > 32 * 1024 * 1024:
            raise ValueError(f"source exceeds 32 MiB: {url}")
        if urlsplit(url).path.lower().endswith(".pdf") and not content.startswith(b"%PDF-"):
            raise ValueError(f"expected PDF, received another format: {url}")
        return content


def decode_html(content):
    match = re.search(rb'charset\s*=\s*["\']?([a-zA-Z0-9_-]+)', content[:4096], re.IGNORECASE)
    encoding = match[1].decode('ascii') if match else 'utf-8'
    if encoding.lower() in {'shift_jis', 'shift-jis', 'sjis'}:
        encoding = 'cp932'
    return content.decode(encoding)


class PdfLinks(HTMLParser):
    def __init__(self, base, hosts=(HOST,)):
        super().__init__()
        self.base, self.links, self.hosts = base, set(), hosts

    def handle_starttag(self, tag, attrs):
        href = dict(attrs).get("href")
        if tag == "a" and href:
            url = urljoin(self.base, href).split("#")[0]
            if urlsplit(url).path.lower().endswith(".pdf"):
                # A host migration must be reviewed, never silently broaden egress.
                self.links.add(allowed_url(url, self.hosts))


def public_manifest_hash(path):
    manifest = json.loads(path.read_text())
    public = {'academicYear': manifest['academicYear'], 'quarter': manifest['quarter'],
              'sources': [s for s in manifest['sources'] if s['access'] == 'public']}
    return hashlib.sha256(json.dumps(public, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def snapshot(root, fetcher=fetch):
    manifests, urls, gaps = {}, set(), []
    for path in sorted((root / "source-manifest").glob("*.json")):
        content = path.read_bytes()
        manifests[str(path.relative_to(root))] = public_manifest_hash(path)
        manifest = json.loads(content)
        for source in manifest["sources"]:
            if source["access"] != "public":
                continue
            urls.add(allowed_url(source["url"]))
            if source.get("artifactUrl"):
                urls.add(allowed_url(source["artifactUrl"]))
    if not urls:
        raise ValueError("no public sources to poll")
    hashes, documents = {}, {}
    while urls:
        url = min(urls)
        urls.remove(url)
        if url in hashes:
            continue
        content = fetcher(url)
        digest = hashlib.sha256(content).hexdigest()
        hashes[url] = digest
        documents[url] = content
        if not urlsplit(url).path.lower().endswith(".pdf"):
            parser = PdfLinks(url)
            parser.feed(decode_html(content))
            urls.update(parser.links - hashes.keys())
    return {"schemaVersion": 1, "manifests": manifests, "sources": dict(sorted(hashes.items()))}, documents, gaps


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".exam-runs")
    args = parser.parse_args()
    try:
        current, documents, _ = snapshot(ROOT)
        previous = json.loads((ROOT / STATE).read_text()) if (ROOT / STATE).exists() else None
        changed = current != previous
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "source-state.json").write_text(json.dumps(current, indent=2) + "\n")
        downloads = []
        for url, content in documents.items():
            suffix = ".pdf" if content.startswith(b"%PDF-") else ".html"
            path = args.output_dir / (hashlib.sha256(url.encode()).hexdigest() + suffix)
            path.write_bytes(content)
            downloads.append({"url": url, "path": str(path), "sha256": current["sources"][url],
                              "retrievedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")})
        (args.output_dir / "acquisition.json").write_text(json.dumps({
            "changed": changed, "documents": downloads,
            "sourcePolicy": "public_only; existing manual records are retained",
        }, indent=2) + "\n")
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as output:
                output.write(f"changed={str(changed).lower()}\n")
        print(json.dumps({"changed": changed, "sources": len(documents)}))
    except (OSError, ValueError) as error:
        print(f"exam source polling failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
