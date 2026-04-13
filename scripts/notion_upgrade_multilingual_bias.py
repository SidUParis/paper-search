import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

REPO_ROOT = Path('/home/orange/paper-search')
sys.path.insert(0, str(REPO_ROOT))

for line in (REPO_ROOT / '.env').read_text(encoding='utf-8').splitlines():
    s = line.strip()
    if '=' in s and not s.startswith('#'):
        k, v = s.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

token = os.getenv('NOTION_TOKEN') or os.getenv('NOTION_API_KEY')
if not token:
    raise RuntimeError('Missing Notion token')

headers = {
    'Authorization': f'Bearer {token}',
    'Notion-Version': '2025-09-03',
    'Content-Type': 'application/json',
}

from paper_search.review_projects import load_review_project
from paper_search.review_writeback import (
    REVIEW_PROPERTY_SCHEMAS,
    _block_title,
    _build_page_properties,
    _build_research_card_blocks,
)

DEFAULT_CONFIG = REPO_ROOT / 'review_projects/examples/multilingual-bias-benchmark-landscape.yaml'
DEFAULT_STATE = REPO_ROOT / 'cache/reviews/multilingual-bias-benchmark-landscape/notion_upgrade_state.json'


def req(method, url, **kwargs):
    last = None
    for attempt in range(6):
        try:
            resp = requests.request(method, url, headers=headers, timeout=60, **kwargs)
            if resp.status_code < 300:
                return resp
            if resp.status_code in (429, 500, 502, 503, 504, 520):
                last = RuntimeError(f'{resp.status_code}: {resp.text[:200]}')
                time.sleep(1.0 * (attempt + 1))
                continue
            raise RuntimeError(f'{method} {url} -> {resp.status_code}: {resp.text[:300]}')
        except Exception as e:
            last = e
            if attempt < 5:
                time.sleep(1.0 * (attempt + 1))
            else:
                raise
    raise last


def load_state(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return {
        'version': 2,
        'upgrade_version': '',
        'project_id': 'multilingual-bias-benchmark-landscape',
        'done_page_ids': [],
        'failed': [],
        'updated': 0,
        'skipped_done': 0,
        'started_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'updated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state['updated_at'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')


def ensure_review_properties_direct(source_map: dict[str, str]) -> None:
    for label, ds_id in source_map.items():
        meta = req('GET', f'https://api.notion.com/v1/data_sources/{ds_id}').json()
        existing = set((meta.get('properties') or {}).keys())
        missing = {name: schema for name, schema in REVIEW_PROPERTY_SCHEMAS.items() if name not in existing}
        if missing:
            req('PATCH', f'https://api.notion.com/v1/data_sources/{ds_id}', json={'properties': missing})
            print(json.dumps({'schema_updated_for': label, 'added_properties': sorted(missing.keys())}), flush=True)


def page_looks_upgraded(page_id: str) -> bool:
    page = req('GET', f'https://api.notion.com/v1/pages/{page_id}').json()
    props = page.get('properties') or {}
    summary_items = ((props.get('Review Summary') or {}).get('rich_text') or [])
    summary = ''.join((x.get('plain_text') or (x.get('text') or {}).get('content') or '') for x in summary_items).strip()
    benchmark_role = (((props.get('Benchmark Role') or {}).get('select') or {}).get('name') or '').strip()
    unified_rel = (((props.get('Unified Multilingual BBQ Relevance') or {}).get('select') or {}).get('name') or '').strip()
    children = req('GET', f'https://api.notion.com/v1/blocks/{page_id}/children?page_size=100').json().get('results', [])
    has_review_card = any(_block_title(child) == 'Research Review Card' for child in children)
    return bool(summary and benchmark_role and unified_rel and has_review_card)


def main():
    parser = argparse.ArgumentParser(description='Upgrade multilingual-bias review pages in Notion with richer properties and research-card bodies.')
    parser.add_argument('--config-path', default=str(DEFAULT_CONFIG))
    parser.add_argument('--state-file', default=str(DEFAULT_STATE))
    parser.add_argument('--limit', type=int, default=None, help='Process at most N pending pages this run')
    parser.add_argument('--reset-state', action='store_true', help='Ignore previous done_page_ids and start over')
    parser.add_argument('--force-page-id', action='append', default=[], help='Specific page_id(s) to process even if already marked done')
    parser.add_argument('--bootstrap-from-notion', action='store_true', help='Before writing, mark already-upgraded pages as done by checking current Notion content')
    parser.add_argument('--upgrade-version', default='multilingual-bias-review-card-v2', help='Version tag stored in state; changing it invalidates previous done_page_ids')
    args = parser.parse_args()

    config_path = Path(args.config_path)
    state_path = Path(args.state_file)
    project = load_review_project(config_path)
    review_dir = REPO_ROOT / 'cache' / 'reviews' / project.review_project_id
    records = [json.loads(line) for line in (review_dir / 'records.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    extractions = [json.loads(line) for line in (review_dir / 'extractions.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    extraction_by_page = {row.get('notion_page_id', ''): row for row in extractions}

    if args.reset_state and state_path.exists():
        state_path.unlink()
    state = load_state(state_path)
    if state.get('upgrade_version') and state.get('upgrade_version') != args.upgrade_version:
        state['done_page_ids'] = []
        state['failed'] = []
        state['updated'] = 0
        state['skipped_done'] = 0
    state['upgrade_version'] = args.upgrade_version
    done_page_ids = set(state.get('done_page_ids', []))
    force_page_ids = set(args.force_page_id or [])

    with open(REPO_ROOT / 'topics.json', 'r', encoding='utf-8') as f:
        topics = json.load(f)
    topic = topics[project.source_topic_slug]
    source_map = {
        'ACL': topic['acl_data_source_id'],
        'arxiv': topic['arxiv_data_source_id'],
        'Scholar': topic['scholar_data_source_id'],
    }
    ensure_review_properties_direct(source_map)

    included = [r for r in records if r.get('screening_decision') == 'include']
    if args.bootstrap_from_notion:
        bootstrapped = 0
        for record in included:
            page_id = str(record.get('notion_page_id', '')).strip()
            if not page_id or page_id in done_page_ids:
                continue
            try:
                if page_looks_upgraded(page_id):
                    state['done_page_ids'].append(page_id)
                    done_page_ids.add(page_id)
                    bootstrapped += 1
            except Exception as e:
                print(json.dumps({'bootstrap_check_failed': page_id, 'error': str(e)}), flush=True)
            save_state(state_path, state)
        print(json.dumps({'bootstrapped_done_page_ids': bootstrapped, 'done_total_after_bootstrap': len(done_page_ids)}), flush=True)

    pending = []
    skipped_done = 0
    for record in included:
        page_id = str(record.get('notion_page_id', '')).strip()
        if not page_id:
            continue
        if page_id in done_page_ids and page_id not in force_page_ids:
            skipped_done += 1
            continue
        pending.append(record)

    if args.limit is not None:
        pending = pending[: args.limit]

    print(json.dumps({
        'project_id': project.review_project_id,
        'included_total': len(included),
        'pending_this_run': len(pending),
        'already_done': skipped_done,
        'state_file': str(state_path),
    }, ensure_ascii=False), flush=True)

    updated_this_run = 0
    for idx, record in enumerate(pending, start=1):
        page_id = str(record.get('notion_page_id', '')).strip()
        extraction_row = extraction_by_page.get(page_id)
        effective = dict(record)
        if extraction_row:
            effective.update({k: v for k, v in extraction_row.items() if k != 'extraction'})
        extraction = (extraction_row or {}).get('extraction') or {}
        props = _build_page_properties(effective, extraction, project=project)
        blocks = _build_research_card_blocks(effective, extraction, project=project)
        try:
            req('PATCH', f'https://api.notion.com/v1/pages/{page_id}', json={'properties': props})
            children = req('GET', f'https://api.notion.com/v1/blocks/{page_id}/children?page_size=100').json().get('results', [])
            for child in children:
                if _block_title(child) == 'Research Review Card':
                    try:
                        req('DELETE', f"https://api.notion.com/v1/blocks/{child.get('id')}")
                    except Exception:
                        pass
            req('PATCH', f'https://api.notion.com/v1/blocks/{page_id}/children', json={'children': blocks})
            if page_id not in done_page_ids:
                state['done_page_ids'].append(page_id)
                done_page_ids.add(page_id)
            updated_this_run += 1
            state['updated'] = int(state.get('updated', 0)) + 1
        except Exception as e:
            state.setdefault('failed', []).append({
                'page_id': page_id,
                'title': record.get('title', ''),
                'error': str(e),
                'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            })
            print(json.dumps({'failed_item': record.get('title', ''), 'page_id': page_id, 'error': str(e)}), flush=True)
        save_state(state_path, state)
        if idx % 10 == 0 or idx == len(pending):
            print(json.dumps({
                'progress': idx,
                'pending_total': len(pending),
                'updated_this_run': updated_this_run,
                'done_total': len(done_page_ids),
                'failed_total': len(state.get('failed', [])),
            }), flush=True)
        time.sleep(0.1)

    state['skipped_done'] = int(state.get('skipped_done', 0)) + skipped_done
    save_state(state_path, state)
    print(json.dumps({
        'included_total': len(included),
        'pending_processed': len(pending),
        'updated_this_run': updated_this_run,
        'done_total': len(done_page_ids),
        'skipped_done_this_run': skipped_done,
        'failed_total': len(state.get('failed', [])),
        'state_file': str(state_path),
    }, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
