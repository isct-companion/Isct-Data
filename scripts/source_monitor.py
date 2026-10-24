#!/usr/bin/env python3
"""Hash public source bytes before starting an agent, with exact per-dataset hosts."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
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


def snapshot(root, dataset, fetcher=None):
    if dataset == 'exams':
        state, documents, _ = exam_snapshot(root, fetcher or fetch)
        return state, documents
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
                if content.lstrip().lower().startswith((b'<!doctype', b'<html')):
                    parser = PublicArtifactLinks(url, hosts); parser.feed(decode_html(content))
                    pending.update(parser.links - hashes.keys())
    return {'schemaVersion': 1, 'dataset': dataset, 'sources': dict(sorted(hashes.items()))}, documents


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
