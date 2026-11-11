#!/usr/bin/env python3
"""Hash public source bytes before starting an agent, with exact per-dataset hosts."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urljoin, urlsplit

from check_exam_sources import PdfLinks, allowed_url, decode_html, fetch, snapshot as exam_snapshot
from dataset_rules import DATASETS, source_urls, state_path


class PublicArtifactLinks(PdfLinks):
    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        href = dict(attrs).get('href')
        if tag == 'a' and href:
            url = urljoin(self.base, href).split('#')[0]
            if urlsplit(url).path.endswith('.csv') and urlsplit(self.base).hostname == 'www8.cao.go.jp':
                self.links.add(allowed_url(url, self.hosts))


class VisibleText(HTMLParser):
    """Visible page text and link targets; markup, scripts and styles are ignored."""
    SKIP = {'script', 'style', 'noscript', 'template'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.links, self.depth = [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.depth += 1
        href = dict(attrs).get('href')
        if tag == 'a' and href:
            self.links.append(href.split('#')[0])

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if not self.depth:
            self.parts.append(data)


def is_html(content):
    # The school's XHTML pages start with an XML declaration, before DOCTYPE.
    return bool(re.search(br'<(?:!doctype\s+html|html(?:\s|>))', content[:4096], re.I))


def content_fingerprint(content):
    """Hash what a reviewer can see, so re-encoded bytes alone never wake the agent.

    PDFs hash page text plus drawn lines and rectangles (strike-throughs and
    revision boxes are geometry, not text). Anything unreadable falls back to
    the byte hash, which errs towards running a review."""
    try:
        if content.startswith(b'%PDF-'):
            import io
            import pdfplumber
            pages = []
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                for page in pdf.pages:
                    shapes = sorted(tuple(round(float(item[k]) * 2) / 2 for k in ('x0', 'top', 'x1', 'bottom'))
                                    for item in (*page.lines, *page.rects))
                    pages.append([re.sub(r'\s+', ' ', page.extract_text() or '').strip(), shapes])
            value = json.dumps(pages, ensure_ascii=False)
        elif is_html(content):
            parser = VisibleText(); parser.feed(decode_html(content))
            text = re.sub(r'\s+', ' ', ' '.join(parser.parts)).strip()
            value = json.dumps([text, parser.links], ensure_ascii=False)
        else:
            return hashlib.sha256(content).hexdigest()
    except ImportError:
        raise
    except Exception:  # noqa: BLE001 - an unreadable document means "treat bytes as content"
        return hashlib.sha256(content).hexdigest()
    return hashlib.sha256(value.encode()).hexdigest()


def with_content(state, documents):
    state['content'] = {url: content_fingerprint(documents[url]) for url in sorted(documents)}
    return state


def triage(state, previous):
    """Decide without inference whether official sources really changed since the last review."""
    if previous is None:
        return True, 'no reviewed source baseline is committed yet', []
    if state.get('manifests') != previous.get('manifests'):
        return True, 'source manifests changed', []
    added = sorted(state['sources'].keys() - previous['sources'].keys())
    removed = sorted(previous['sources'].keys() - state['sources'].keys())
    rebytes = sorted(u for u in state['sources'].keys() & previous['sources'].keys()
                     if state['sources'][u] != previous['sources'][u])
    details = [f'added {u}' for u in added] + [f'removed {u}' for u in removed]
    if added or removed:
        return True, 'the set of official sources changed', details + [f'bytes {u}' for u in rebytes]
    if not rebytes:
        return False, 'official source bytes are unchanged', []
    old = previous.get('content')
    if not old:
        return True, 'source bytes changed and the baseline has no content fingerprints', [f'bytes {u}' for u in rebytes]
    changed = [u for u in rebytes if state['content'].get(u) != old.get(u)]
    if not changed:
        return False, 'only markup or encoding changed; visible content is identical', [f'bytes {u}' for u in rebytes]
    return True, 'visible source content changed', [f'content {u}' for u in changed]


def snapshot(root, dataset, fetcher=None):
    if dataset == 'exams':
        state, documents, _ = exam_snapshot(root, fetcher or fetch)
        return with_content(state, documents), documents
    hosts = DATASETS[dataset]['hosts']
    pending = {allowed_url(url, hosts) for url in source_urls(root, dataset)}
    if not pending:
        raise ValueError('no public sources configured')
    hashes, documents = {}, {}
    downloader = fetcher or (lambda url: fetch(url, hosts))
    with ThreadPoolExecutor(max_workers=4) as pool:
        while pending:
            if len(hashes) + len(pending) > 256:
                raise ValueError('public source graph exceeds 256 resources')
            batch = sorted(pending); pending = set()
            for url, content in zip(batch, pool.map(downloader, batch)):
                hashes[url] = hashlib.sha256(content).hexdigest(); documents[url] = content
                if sum(map(len, documents.values())) > 256 * 1024 * 1024:
                    raise ValueError('public source graph exceeds 256 MiB')
                if is_html(content):
                    parser = PublicArtifactLinks(url, hosts); parser.feed(decode_html(content))
                    pending.update(parser.links - hashes.keys())
    state = {'schemaVersion': 1, 'dataset': dataset, 'sources': dict(sorted(hashes.items()))}
    return with_content(state, documents), documents


def acquire(root, dataset):
    state, documents = snapshot(root, dataset)
    directory = root / '.data-runs'; directory.mkdir(exist_ok=True)
    downloads = directory / 'sources'; downloads.mkdir(exist_ok=True)
    # The exam writer keeps its established run paths; no tracked data is changed here.
    if dataset == 'exams':
        (root / '.exam-runs').mkdir(exist_ok=True)
    records = []
    for url, content in sorted(documents.items()):
        suffix = '.pdf' if content.startswith(b'%PDF-') else ('.csv' if urlsplit(url).path.endswith('.csv') else '.html')
        stem = Path(urlsplit(url).path).stem or 'index'
        name = f'{stem}-{hashlib.sha256(url.encode()).hexdigest()[:10]}{suffix}'
        path = downloads / name; path.write_bytes(content)
        records.append({'url': url, 'path': str(path.relative_to(root)), 'sha256': state['sources'][url],
                        'retrievedAt': datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')})
    (directory / 'source-state.json').write_text(json.dumps(state, indent=2) + '\n')
    (directory / 'acquisition.json').write_text(json.dumps({'dataset': dataset, 'documents': records}, indent=2) + '\n')
    if dataset == 'exams':
        (root / '.exam-runs/source-state.json').write_text(json.dumps(state, indent=2) + '\n')
    return state, records
