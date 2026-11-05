"""VNext retrieval contracts using deterministic vectors and temporary artifacts."""
from pathlib import Path
import json
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.retrieval_service.config import load_config
from services.retrieval_service.indexing.vnext_artifacts import build_candidate, load_candidate
from services.retrieval_service.indexing.vnext_retrieval import CandidateRuntime, reciprocal_rank_fusion
from services.retrieval_service.indexing.vnext_evaluation import case_metrics, evaluate_candidates, validate_cases


def chunks():
    texts = [('doc-a', 'pump flow pressure cold plate', 'reviewed'),
             ('doc-a', 'pump flow pressure coolant', 'machine_draft'),
             ('doc-b', 'thermal resistance junction temperature', 'published'),
             ('doc-c', 'sensor calibration measurement uncertainty', 'pending_review')]
    return [{'chunk_id': f'chunk-{i}', 'source_id': doc, 'document_sha256': str(i//2)*64,
             'text': text, 'page_start': 1, 'page_end': 1, 'review_status': review,
             'section_path': ['Test section'], 'parent_id': None,
             'source_spans': [{'block_id': f'b{i}', 'start': 0, 'end': len(text), 'page': 1}],
             'quality_flags': []} for i, (doc, text, review) in enumerate(texts)]


def embed(texts):
    return np.array([[1., .01, 0.] if 'pump' in t else [.01, 1., 0.] if 'thermal' in t else [0., .01, 1.] for t in texts], dtype=np.float32)


class VNextRetrievalTest(unittest.TestCase):
    def build(self, path, records=None, provider=embed, **kwargs):
        return build_candidate(records or chunks(), path, embed_batch=provider,
                               model_identity={'name': 'deterministic-test-fixture', 'revision': '1'},
                               chunk_strategy='fixture', batch_size=2, **kwargs)

    def test_safe_unicode_artifacts_roundtrip_without_pickle(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'中文候选'
            self.build(path)
            artifact = load_candidate(path)
            self.assertEqual([r['chunk_id'] for r in artifact['chunks']], ['chunk-0','chunk-1','chunk-2','chunk-3'])
            self.assertEqual(artifact['vectors'].shape, (4,3))
            self.assertFalse(list(path.rglob('*.pkl')))
            self.assertFalse(artifact['manifest']['production_activation_allowed'])
            self.assertEqual(artifact['manifest']['tokenizer_version'], 'thermal_lexical_v2')

    def test_interrupted_batch_resumes_only_verified_checkpoints(self):
        calls=[]
        def fail(texts):
            calls.append(texts)
            if len(calls)==2: raise RuntimeError('simulated interruption')
            return embed(texts)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'resume'
            with self.assertRaises(RuntimeError): self.build(path,provider=fail)
            resumed=[]
            self.build(path,provider=lambda t:(resumed.extend(t) or embed(t)),resume=True)
            self.assertEqual(len(resumed),2)
            self.assertEqual(load_candidate(path)['manifest']['chunk_count'],4)
            with self.assertRaises((ValueError,FileExistsError)): self.build(path)

    def test_content_tampering_rejected_before_loading_faiss(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'candidate'; self.build(path)
            file=path/'chunks.jsonl'; file.write_text(file.read_text(encoding='utf-8')+'\n',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'hash'): load_candidate(path)

    def test_invalid_source_identity_vector_and_unknown_version_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            records=chunks(); records[1]['chunk_id']=records[0]['chunk_id']
            with self.assertRaises(ValueError): self.build(Path(temp)/'duplicate',records)
            with self.assertRaises(ValueError): self.build(Path(temp)/'zero',provider=lambda t:np.zeros((len(t),3)))
            path=Path(temp)/'version'; self.build(path)
            mf=path/'manifest.json'; manifest=json.loads(mf.read_text(encoding='utf-8')); manifest['schema_version']='unknown'
            mf.write_text(json.dumps(manifest),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'version'): load_candidate(path)

    def test_reciprocal_rank_fusion_uses_rank_not_score_scale(self):
        scores=reciprocal_rank_fusion([['a','b'],['b','a']],rank_constant=60)
        self.assertAlmostEqual(scores['a'],scores['b'])
        self.assertAlmostEqual(scores['a'],1/61+1/62)
        self.assertEqual(reciprocal_rank_fusion([['a','a']],rank_constant=60)['a'],1/61)

    def test_true_dense_and_bm25_channels_and_production_hybrid(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'candidate';self.build(path)
            runtime=CandidateRuntime(path,cfg=load_config(),embed_query=lambda q:embed([q]))
            modes=runtime.search('thermal resistance',top_k=3)
            self.assertEqual(modes['dense_only']['results'][0]['chunk_id'],'chunk-2')
            self.assertEqual(modes['bm25_only']['results'][0]['chunk_id'],'chunk-2')
            self.assertIn('original_hybrid',modes)
            self.assertEqual(modes['original_hybrid']['implementation'],'production_query_plan_merge_rerank')

    def test_metadata_filters_cannot_reintroduce_rejected_source(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'candidate';self.build(path)
            runtime=CandidateRuntime(path,cfg=load_config(),embed_query=lambda q:embed([q]))
            modes=runtime.search('pump flow',top_k=4,filters={'review_status':['reviewed','published'],'source_ids':['doc-a']})
            for result in modes.values():
                self.assertTrue(all(r['chunk_id']=='chunk-0' for r in result['results']))

    def test_diversification_limits_one_document_without_fabricating_hits(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'candidate';self.build(path)
            runtime=CandidateRuntime(path,cfg=load_config(),embed_query=lambda q:embed([q]))
            result=runtime.search('pump flow',top_k=3)['rrf_mmr']['results']
            self.assertEqual(len({r['source_id'] for r in result}),len(result))
            self.assertTrue(all(r['chunk_id'] in {c['chunk_id'] for c in chunks()} for r in result))

    def test_machine_references_never_become_formal_gold(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'candidate';self.build(path)
            case={'case_id':'dev1','query':'thermal resistance','split':'development','label_status':'machine_reference','relevant_chunk_ids':['chunk-2']}
            result=evaluate_candidates({'fixed':CandidateRuntime(path,cfg=load_config(),embed_query=lambda q:embed([q]))},[case],top_k=3)
            self.assertEqual(result['formal_metrics']['top5_hit_rate']['status'],'unavailable')
            self.assertFalse(result['production_activation_allowed'])
            self.assertEqual(result['results'][0]['modes']['dense_only']['metrics']['hit_at_k'],1)

    def test_split_leakage_and_unsigned_human_gold_are_rejected(self):
        case={'case_id':'dev1','query':'Pump flow?', 'split':'development','label_status':'machine_reference','relevant_chunk_ids':['chunk-0']}
        with self.assertRaises(ValueError): validate_cases([case,{**case,'case_id':'test1','split':'test'}])
        with self.assertRaises(ValueError): validate_cases([{**case,'label_status':'human_reviewed','split':'test'}])

    def test_recall_precision_and_hit_have_distinct_denominators(self):
        case={'case_id':'metric','query':'thermal','split':'development','label_status':'machine_reference',
              'relevant_chunk_ids':['chunk-0','chunk-1']}
        result=case_metrics(case,chunks()[:1],5)
        self.assertEqual(result['hit_at_k'],1)
        self.assertEqual(result['recall_at_k'],.5)
        self.assertEqual(result['precision_at_k'],.2)
        self.assertEqual(result['precision_returned'],1.)

    def test_span_labels_transfer_across_chunk_ids_without_inflating_coverage(self):
        case={'case_id':'span','query':'thermal','split':'validation','label_status':'machine_reference',
              'relevant_spans':[{'source_id':'doc-a','block_id':'b0','start':0,'end':20}], 'is_negative':False}
        normalized=validate_cases([case])[0]
        record=chunks()[0]; record['chunk_id']='different-strategy-id'
        record['source_spans'][0]['end']=9
        self.assertEqual(case_metrics(normalized,[record],5)['hit_at_k'],0)
        record['source_spans'][0]['end']=10
        self.assertEqual(case_metrics(normalized,[record],5)['hit_at_k'],1)
        record['source_id']='unrelated-document'
        self.assertEqual(case_metrics(normalized,[record],5)['hit_at_k'],0)

    def test_explicit_negative_cases_and_unknown_labels_are_not_zero_recall(self):
        case={'case_id':'neg','query':'unanswerable','split':'test','label_status':'machine_reference',
              'is_negative':True,'relevant_spans':[]}
        normalized=validate_cases([case])[0]
        result=case_metrics(normalized,chunks()[:1],5)
        self.assertIsNone(result['recall_at_k'])
        self.assertEqual(result['unanswerable_return_rate'],1)
        self.assertEqual(case_metrics(normalized,[],5)['unanswerable_return_rate'],0)
        with self.assertRaises(ValueError): validate_cases([{**case,'relevant_chunk_ids':['chunk-0']}])

    def test_unknown_filter_and_invalid_pool_rejected_before_query_embedding(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'candidate';self.build(path)
            calls=[]
            runtime=CandidateRuntime(path,cfg=load_config(),embed_query=lambda q:(calls.append(q) or embed([q])))
            with self.assertRaises(ValueError): runtime.search('pump',filters={'source_id':['doc-a']})
            with self.assertRaises(ValueError): runtime.search('pump',top_k=5,pool_size=2)
            with self.assertRaises(ValueError): runtime.search('pump',mmr_lambda=float('nan'))
            self.assertFalse(calls)

    def test_same_corpus_comparison_rejects_different_source_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            one,two=Path(temp)/'one',Path(temp)/'two';self.build(one)
            rows=chunks(); rows[-1]['source_id']='new-source';self.build(two,rows)
            runtimes={name:CandidateRuntime(path,cfg=load_config(),embed_query=lambda q:embed([q])) for name,path in [('a',one),('b',two)]}
            case={'case_id':'1','query':'pump','split':'development','label_status':'machine_reference','relevant_chunk_ids':['chunk-0']}
            with self.assertRaisesRegex(ValueError,'source collections'): evaluate_candidates(runtimes,[case])

    def test_parent_child_returns_exact_original_parent_with_separate_provenance(self):
        from scripts.evaluate_vnext_retrieval import load_chunk_inputs
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp); rows=chunks(); parent={**rows[0],'chunk_id':'parent-0','parent_id':None}
            child={**rows[0],'parent_id':'parent-0'}
            (folder/'chunks.jsonl').write_text(json.dumps(child)+'\n',encoding='utf-8')
            (folder/'parents.jsonl').write_text(json.dumps(parent)+'\n',encoding='utf-8')
            loaded=load_chunk_inputs(folder/'chunks.jsonl','parent_child')
            self.assertEqual(loaded[0]['parent_context']['text'],parent['text'])
            self.build(folder/'candidate',loaded)
            runtime=CandidateRuntime(folder/'candidate',cfg=load_config(),embed_query=lambda q:embed([q]))
            hit=runtime.search('pump flow',top_k=1)['dense_only']['results'][0]
            self.assertEqual(hit['parent_context']['chunk_id'],'parent-0')
            self.assertEqual(hit['text'],child['text'])
            parent['source_id']='forged-source'
            (folder/'parents.jsonl').write_text(json.dumps(parent)+'\n',encoding='utf-8')
            with self.assertRaises(ValueError): load_chunk_inputs(folder/'chunks.jsonl','parent_child')

    def test_cli_evaluates_precomputed_vectors_without_model_or_database(self):
        from scripts.evaluate_vnext_retrieval import main
        from services.retrieval_service.query_analyzer import analyze_query
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp); path=folder/'candidate';self.build(path)
            case={'case_id':'cli','query':'thermal resistance','split':'development','label_status':'machine_reference',
                  'relevant_chunk_ids':['chunk-2']}
            (folder/'cases.json').write_text(json.dumps([case]),encoding='utf-8')
            queries=set(analyze_query(load_config(),case['query']).vector_queries())|{case['query']}
            (folder/'queries.json').write_text(json.dumps({q:embed([q])[0].tolist() for q in queries}),encoding='utf-8')
            code=main(['evaluate','--candidate',f'fixed={path}','--cases',str(folder/'cases.json'),
                       '--query-vectors',str(folder/'queries.json'),'--output-dir',str(folder/'evaluation')])
            self.assertEqual(code,0)
            result=json.loads((folder/'evaluation'/'results.json').read_text(encoding='utf-8'))
            self.assertEqual(result['case_count'],1)
            self.assertEqual(result['model']['provider'],'precomputed_query_vectors')
            self.assertFalse(result['production_activation_allowed'])

    def test_incompatible_model_cannot_resume_existing_embeddings(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'resume';count=[]
            def fail(texts):
                count.append(1)
                if len(count)>1: raise RuntimeError('interrupted')
                return embed(texts)
            with self.assertRaises(RuntimeError): self.build(path,provider=fail)
            with self.assertRaisesRegex(ValueError,'resume inputs'):
                build_candidate(chunks(),path,embed_batch=embed,model_identity={'name':'other-model','revision':'2'},
                                chunk_strategy='fixture',batch_size=2,resume=True)

    def test_source_symbol_fragment_is_preserved_without_inventing_sparse_words(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'candidate';rows=chunks();rows[-1]['text']='+'
            rows[-1]['source_spans'][0]['end']=1
            self.build(path,rows)
            artifact=load_candidate(path)
            self.assertEqual(artifact['manifest']['bm25_empty_document_count'],1)
            self.assertEqual(artifact['chunks'][-1]['text'],'+')
            self.assertEqual(artifact['bm25']['tokens'][-1],[])
            runtime=CandidateRuntime(path,cfg=load_config(),embed_query=lambda q:embed([q]))
            result=runtime.search('symbol',top_k=1,filters={'source_ids':['doc-c']})
            self.assertEqual(result['bm25_only']['results'],[])
            self.assertTrue(all(row['source_id']=='doc-c' for mode in result.values() for row in mode['results']))

    def test_legacy_snapshot_keeps_original_ids_and_explicit_db_span_scope(self):
        from services.retrieval_service.indexing.vnext_legacy import legacy_rows, convert_legacy_cases
        catalog={12:{'document_id':3,'text':'original thermal text','page_start':2,'page_end':2}}
        docs={3:{'sha256':'a'*64,'title':'Original source'}}
        rows=legacy_rows([(12,0)],catalog,docs)
        self.assertEqual(rows[0]['chunk_id'],'legacy_chunk_12')
        self.assertEqual(rows[0]['source_id'],'legacy_doc_3')
        self.assertEqual(rows[0]['text'],'original thermal text')
        self.assertEqual(rows[0]['span_coordinate_system'],'legacy_database_chunk_text_not_pdf_block')
        with self.assertRaises(ValueError): legacy_rows([(12,1)],catalog,docs)
        cases=convert_legacy_cases({'cases':[{'case_id':'neg01','query':'distinguish physics',
                                            'relevant_chunk_ids':[12],'expected_document_ids':[3],'forbidden_document_ids':[8]}]})
        self.assertTrue(cases[0]['answerable'])
        self.assertEqual(cases[0]['forbidden_source_ids'],['legacy_doc_8'])
        self.assertEqual(cases[0]['label_status'],'machine_reference')

    def test_expansion_comparison_requires_exact_preservation_of_base_chunks(self):
        with tempfile.TemporaryDirectory() as temp:
            one,two=Path(temp)/'one',Path(temp)/'two';self.build(one)
            extra={**chunks()[-1],'chunk_id':'new-chunk','source_id':'new-source','document_sha256':'a'*64}
            self.build(two,chunks()+[extra])
            runtime=lambda p:CandidateRuntime(p,cfg=load_config(),embed_query=lambda q:embed([q]))
            case={'case_id':'1','query':'pump','split':'development','label_status':'machine_reference','relevant_chunk_ids':['chunk-0']}
            result=evaluate_candidates({'base':runtime(one),'expanded':runtime(two)},[case],comparison_mode='corpus_expansion')
            self.assertEqual(result['comparison_mode'],'corpus_expansion')
            self.assertIsNone(result['source_collection_version'])
            self.assertFalse(result['production_activation_allowed'])
            rows=chunks()+[extra];rows[0]['text']='changed source body'
            three=Path(temp)/'three';self.build(three,rows)
            with self.assertRaisesRegex(ValueError,'changed the base chunk'):
                evaluate_candidates({'base':runtime(one),'bad':runtime(three)},[case],comparison_mode='corpus_expansion')

    def test_semantic_resume_rejects_changed_body_even_when_spans_look_valid(self):
        from types import SimpleNamespace
        from scripts.evaluate_vnext_retrieval import _semantic_chunks
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);output=folder/'out';output.mkdir()
            document={'document':{'source_id':'fixture','sha256':'a'*64,'source_document_version':'1'},
                      'blocks':[{'block_id':'b0','kind':'paragraph','page':1,'bbox':[0,0,10,10],
                                 'text':'Pump flow affects heat transfer.','order':0,'section_path':[],
                                 'quality_flags':[],'relations':[]}]}
            parsed=folder/'parsed.json';parsed.write_text(json.dumps(document),encoding='utf-8')
            report=folder/'parser.json';report.write_text(json.dumps({'policy':{'options':{}},'records':[{'status':'parsed','source_id':'fixture','parsed_path':str(parsed)}]}),encoding='utf-8')
            session=SimpleNamespace(policy={'fixture':True},identity={'name':'fixture','revision':'1'},documents=lambda texts:np.ones((len(texts),2)))
            _semantic_chunks(report,output,session,resume=False)
            manifest=json.loads((output/'semantic_chunks'/'manifest.json').read_text(encoding='utf-8'))
            cached=Path(manifest['records'][0]['result_path'])
            result=json.loads(cached.read_text(encoding='utf-8'));result['chunks'][0]['text']='INVENTED'
            cached.write_text(json.dumps(result),encoding='utf-8')
            with self.assertRaises(ValueError): _semantic_chunks(report,output,session,resume=True)

    def test_completed_progress_recovery_rejects_missing_duplicate_and_forged_evidence(self):
        from copy import deepcopy
        from services.retrieval_service.indexing.vnext_evaluation import recover_completed_records
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'candidate';self.build(path)
            runtime=CandidateRuntime(path,cfg=load_config(),embed_query=lambda q:embed([q]))
            cases=[{'case_id':'recovery','query':'pump flow','split':'development','label_status':'machine_reference',
                    'relevant_chunk_ids':['chunk-0']}]
            original=evaluate_candidates({'fixture':runtime},cases)
            artifacts={'fixture':load_candidate(path)}
            recovered=recover_completed_records(artifacts,cases,original['results'])
            self.assertEqual(recovered['summary'],original['summary'])
            self.assertFalse(recovered['recovery']['retrieval_executed_during_recovery'])
            with self.assertRaises(ValueError): recover_completed_records(artifacts,cases,[])
            with self.assertRaises(ValueError): recover_completed_records(artifacts,cases,original['results']*2)
            forged=deepcopy(original['results']);forged[0]['modes']['dense_only']['results'][0]['text']='forged source text'
            with self.assertRaisesRegex(ValueError,'evidence'): recover_completed_records(artifacts,cases,forged)
            altered=deepcopy(original['results']);altered[0]['modes']['dense_only']['metrics']['hit_at_k']=99
            with self.assertRaisesRegex(ValueError,'metrics'): recover_completed_records(artifacts,cases,altered)


if __name__=='__main__': unittest.main()
