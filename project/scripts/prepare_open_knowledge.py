"""Prepare immutable, evidence-checked knowledge/QA candidates from a parser run."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from html import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.ingest_service.knowledge.open_candidates import build_candidates
from services.ingest_service.knowledge.question_candidates import build_questions
from services.ingest_service.knowledge.staging_io import read_json, verify_source_files, write_import_package, validate_import_package, write_json_exclusive
from services.ingest_service.knowledge.staging_contracts import content_hash
from services.ingest_service.knowledge.staging_store import make_record


def write_review_index(path: Path, units: list[dict], questions: list[dict]):
    """Readable local review packet; no form can silently approve a record."""
    cards = []
    for kind, rows in (('KU', units), ('QA', questions)):
        for row in rows:
            identity = row.get('candidate_id') or row['case_id']
            title = row.get('title') or row['query']
            tags = ', '.join(row.get('domain_tags') or [row.get('category','')])
            references = row.get('evidence') or row.get('relevant_spans') or []
            links = []
            for evidence in references:
                url = evidence.get('url') or evidence.get('source_url') or ''
                if url.startswith('https://'):
                    links.append('<a href="'+escape(url,quote=True)+'" target="_blank" rel="noreferrer">'+
                                 escape(evidence['source_id'])+'</a> · page '+escape(str(evidence.get('page')))+
                                 ' · '+escape(evidence.get('block_id','')))
            content = row.get('claim') or row.get('reference_answer','')
            cards.append('<details class="card"><summary><span>'+kind+' · 待审核</span> '+escape(title)+
                         '</summary><p>'+escape(identity)+' · '+escape(tags)+'</p><p>'+ '<br>'.join(links)+
                         '</p><pre>'+escape(content)+'</pre><details><summary>完整字段、原文与审核提示</summary><pre>'+
                         escape(json.dumps(row,ensure_ascii=False,indent=2))+'</pre></details></details>')
    html = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ThermalAgent 待审核资料包</title><style>body{font:16px/1.65 system-ui;margin:32px auto;max-width:1080px;padding:0 20px;color:#172c3d;background:#f6f8fa}h1{font-size:27px}input{font:inherit;padding:12px;width:95%;border:1px solid #a7b5be;border-radius:6px}details.card{background:white;border:1px solid #d3dde3;border-radius:8px;margin:12px 0;padding:16px}summary{cursor:pointer}span{color:#936415;font-size:13px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f0f4f7;padding:12px;font:14px/1.6 ui-monospace,monospace}a{color:#125f87}.notice{padding:18px;background:#fff4da;border-left:4px solid #ae7b20}</style>
<h1>ThermalAgent 能源专业审核资料包</h1><p class="notice">全部为机器候选。原文可定位不等于命题、数值、单位或答案已经专业审核。此页面仅供阅读，不会写数据库或授予审核状态。请核对PDF原页、适用范围、表头、上下标和同义重复，并在随附空白表单记录实际审核。</p>
<input id="filter" placeholder="搜索题目、领域、来源或候选ID" aria-label="筛选候选"><p id="count"></p>
''' + '\n'.join(cards) + '''<script>const cards=[...document.querySelectorAll('.card')];function filter(){const q=document.querySelector('#filter').value.toLowerCase();let n=0;for(const c of cards){c.hidden=!c.textContent.toLowerCase().includes(q);if(!c.hidden)n++;}document.querySelector('#count').textContent=`显示 ${n} / ${cards.length} 项`;};document.querySelector('#filter').addEventListener('input',filter);filter();</script></html>'''
    path.write_text(html,encoding='utf-8')


def prepare(source_manifest, parsed_run, seeds, output, *, strategy='engineering', prior_questions=(), numeric_specs=None):
    result = read_json(parsed_run / 'results.json')
    if not result.get('completed'):
        raise ValueError('parser_run_incomplete')
    verified = verify_source_files([s for s in source_manifest['sources'] if s.get('status') == 'downloaded'], ROOT)
    if verified['rejected']:
        raise ValueError('source_integrity_or_permission_failed')
    sources = verified['accepted']
    documents = [read_json(ROOT / r['parsed_path']) for r in result['records'] if r.get('status') == 'parsed']
    if {d['document']['source_id'] for d in documents} != {s['source_id'] for s in sources}:
        raise ValueError('parsed_downloaded_source_set_differs')
    by_source = {s['source_id']:s for s in sources}
    for doc in documents:
        original_metadata = doc['document'].get('metadata', {})
        latest = by_source[doc['document']['source_id']]
        if original_metadata != latest:
            doc['document']['parser_source_metadata_snapshot_sha256'] = content_hash(original_metadata)
            doc['document']['metadata'] = latest
            doc['document']['metadata_resolution'] = 'current source ledger; raw parser artifact preserved'
    units = build_candidates(documents, sources)
    question_result = build_questions(seeds, documents, sources, existing_queries=prior_questions)
    output.mkdir(parents=True, exist_ok=False)
    write_json_exclusive(output / 'question_build.json', question_result)
    if question_result['rejected']:
        raise ValueError('qa_anchor_or_duplicate_check_failed: inspect question_build.json')
    from services.ingest_service.knowledge.numeric_quality import assess_record_numeric_quality
    numeric_specs = numeric_specs or {}
    question_by_id = {q['case_id']:q for q in question_result['questions']}
    if set(numeric_specs) - set(question_by_id):
        raise ValueError('numeric_spec_references_unknown_question')
    quality = {'scope':'Explicit arithmetic and units only; no source or professional certification',
               'human_reviewed_increment':0, 'qa_checks':[], 'unit_checks':[]}
    for case_id, spec in numeric_specs.items():
        item = {'case_id':case_id, 'question_version_id':question_by_id[case_id]['version_id'],
                'spec':spec,'result':assess_record_numeric_quality({'arithmetic_spec':spec})}
        quality['qa_checks'].append(item)
    for unit in units['candidates']:
        quality['unit_checks'].append({'candidate_id':unit['candidate_id'],'version_id':unit['version_id'],
            'result':assess_record_numeric_quality(unit)})
    if any(item['result']['status']=='failed' for item in quality['qa_checks']+quality['unit_checks']):
        write_json_exclusive(output/'numeric_quality.json',quality)
        raise ValueError('explicit_numeric_quality_failed')
    units['numeric_quality'] = quality
    write_json_exclusive(output/'numeric_quality.json',quality)
    path = parsed_run / strategy / 'chunks.jsonl'
    chunks = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    if not chunks:
        raise ValueError('empty_chunk_strategy')
    write_import_package(output / 'package', sources=sources, documents=documents, chunks=chunks,
                         candidate_result=units, questions=question_result['questions'])
    checked = validate_import_package(output / 'package', project_root=ROOT)
    write_json_exclusive(output / 'validation.json', {'checks': checked['checks'], 'manifest': checked['manifest']})
    review = output / 'expert_review'
    review.mkdir()
    for name, rows in (('unit_tasks', units['candidates']), ('question_tasks', question_result['questions'])):
        (review / (name + '.jsonl')).write_text(''.join(json.dumps(r, ensure_ascii=False, allow_nan=False) + '\n' for r in rows), encoding='utf-8')
    templates = [{'record_id':make_record('unit',u)['record_id'], 'candidate_id': u['candidate_id'], 'version_id': u['version_id'], 'claim_sha256': u['claim_sha256'],
                  'origin': None, 'reviewer': '', 'reviewed_at': '', 'decision': None,
                  'independent_of_generator': None, 'domain_expertise_confirmed': None, 'rationale': ''}
                 for u in units['candidates']]
    write_json_exclusive(review / 'unfilled_review_forms.json', templates)
    write_review_index(review / 'review.html', units['candidates'], question_result['questions'])
    (review / 'README.md').write_text(
        '# 专业审核资料包\n\n所有条目仍为机器候选，表单为空不表示审核。\n\n'
        'unit_tasks.jsonl 含完整原文、页码/bbox、单位识别提示和冲突关联。先核对PDF原页，特别是上下标、负号、单位及表头；'
        '再审核工程命题、适用条件和独立性。一个段落候选不等于一个有效知识点，需合并同义条目并拆解复合命题后重新绑定版本。\n\n'
        'question_tasks.jsonl 含新题、参考答案和原文块。审核答案正确性、证据充分性、参数、工具/图形/原因标签，排除旧题语义重复。'
        '当前test分组只有机器标签，不是独立gold；正式测试需独立专家标注、版本冻结和开发人员访问隔离。\n\n'
        'unfilled_review_forms.json 仅是待填写表单。审核人必须明确身份、时间、专业资质及理由；服务只记录外部声明，不能认证真实身份。'
        '所有真实专家审核与正式索引发布仍待执行。\n', encoding='utf-8')
    summary = {'units': units['summary'], 'qa': question_result['summary'], 'package': checked['manifest']['counts'],
               'database_written': False, 'production_index_activated': False}
    write_json_exclusive(output / 'result.json', summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-manifest', type=Path, required=True)
    parser.add_argument('--parsed-run', type=Path, required=True)
    parser.add_argument('--qa-seeds', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--strategy', choices=['fixed','structure','semantic','parent_child','engineering'], default='engineering')
    parser.add_argument('--prior-qa', type=Path, default=ROOT / 'data/evaluation/coolingqa_liquid_30.json')
    parser.add_argument('--numeric-specs', type=Path, help='Optional explicit arithmetic specifications keyed by draft case_id; no OCR expression execution.')
    args = parser.parse_args()
    if not args.output_dir.resolve().is_relative_to(ROOT):
        parser.error('output must stay inside the project')
    prior = read_json(args.prior_qa)
    prior = prior.get('cases', []) if isinstance(prior, dict) else prior
    print(json.dumps(prepare(read_json(args.source_manifest), args.parsed_run, read_json(args.qa_seeds), args.output_dir,
        strategy=args.strategy, prior_questions=[q.get('query') or q.get('question') or '' for q in prior],
        numeric_specs=read_json(args.numeric_specs) if args.numeric_specs else None), ensure_ascii=False))


if __name__ == '__main__':
    main()
