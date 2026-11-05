"""Real BM25/FAISS lexical contracts; synthetic corpus, no database or model calls."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import pickle
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from services.retrieval_service.bm25_index import BM25IndexManager, bm25_tokenize, load_bm25_payload, rebuild_bm25_index
from services.retrieval_service.bm25_tokenizer import CURRENT_TOKENIZER_VERSION, LEGACY_TOKENIZER_VERSION
from services.retrieval_service.config import load_config
from services.retrieval_service.indexing import candidate_builder, index_validator
from services.retrieval_service.indexing.diagnostics.runner import DiagnosticRuntime
from services.retrieval_service.indexing.holdout_evaluator import _BundleRuntime
from services.retrieval_service.indexing.explicit_bundles import build_candidate_bundle
from scripts.retrieval_artifact_fixtures import synthetic_index_environment, deterministic_vectors


class TokenizerContractTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='bm25-contract-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.cfg=load_config(self.root)
        self.manager=BM25IndexManager(self.cfg)

    def write_legacy(self):
        texts=['Pump thermal','PUMP cooling','pump water','sensor leakage','cold plate']
        self.manager.ensure_dir()
        payload={'chunk_ids':list(range(5)), 'tokenized_corpus':[bm25_tokenize(t,version=LEGACY_TOKENIZER_VERSION) for t in texts], 'corpus_texts':texts}
        self.cfg.paths.bm25_corpus_path.write_bytes(pickle.dumps(payload))
        self.cfg.paths.bm25_meta_path.write_text(json.dumps({'chunk_count':5}),encoding='utf-8')
        return texts

    def test_contiguous_chinese_and_english_normalization(self):
        self.assertEqual(bm25_tokenize('热阻；TIM 冷板 800W 温升'),['tim','800W','热阻','冷板','温升'])
        self.assertEqual(bm25_tokenize('Pump CPU thermal.'),bm25_tokenize('PUMP cpu THERMAL.'))
        self.assertEqual(bm25_tokenize('热阻；TIM 冷板',version=LEGACY_TOKENIZER_VERSION),['TIM','热阻','阻冷','冷板'])

    def test_units_and_attached_numbers_remain_case_sensitive(self):
        symbols=['W','mW','MW','Pa','kPa','MPa','mPa','hPa','mbar','mHz','degC','degF','Cal','cal','m','mm','M','K','k','LPM','L/min','kg/s','m3/s','800W','30kPa','1e-3m']
        for symbol in symbols:
            with self.subTest(symbol=symbol):
                self.assertEqual(bm25_tokenize(symbol),[symbol])
        self.assertNotEqual(bm25_tokenize('1 mW'),bm25_tokenize('1 MW'))
        for value in ['W/(m*K)','J/(kg*K)','图1-2；表3.4；式5-6']:
            tokens=bm25_tokenize(value)
            for part in re.findall(r'[A-Za-z]+|\d+(?:[-.]\d+)*',value):
                self.assertIn(part,' '.join(tokens))

    def test_existing_tool_and_physics_unit_spellings_are_preserved(self):
        from typing import get_args
        from services.physics_service.contracts import Unit
        from services.retrieval_service.tools.specs import TOOL_SPECS
        units=set(get_args(Unit))
        for spec in TOOL_SPECS.values():
            units.update(spec.units.values())
        for unit in units:
            tokens=' '.join(bm25_tokenize(unit))
            for atom in re.findall(r'[A-Za-z]+',unit):
                with self.subTest(unit=unit,atom=atom):
                    self.assertIn(atom,tokens)

    def test_new_index_search_uses_same_lexical_contract_as_documents(self):
        texts=['PUMP thermal path','sensor leakage','cold plate','water cooling','junction resistance']
        self.manager.save(chunk_ids=list(range(5)),tokenized_corpus=[bm25_tokenize(t) for t in texts],corpus_texts=texts)
        payload,version=load_bm25_payload(self.cfg.paths.bm25_corpus_path,self.cfg.paths.bm25_meta_path)
        self.assertEqual(version,CURRENT_TOKENIZER_VERSION)
        self.assertEqual(payload['tokenizer_version'],CURRENT_TOKENIZER_VERSION)
        self.assertEqual(self.manager.search('PUMP'),self.manager.search('pump'))
        self.assertEqual(self.manager.search('Pump')[0][0],0)

    def test_legacy_unversioned_pickle_keeps_original_queries_and_bytes(self):
        self.write_legacy()
        paths=[self.cfg.paths.bm25_corpus_path,self.cfg.paths.bm25_meta_path]
        hashes=[sha256(p.read_bytes()).hexdigest() for p in paths]
        _,version=load_bm25_payload(*paths)
        self.assertEqual(version,LEGACY_TOKENIZER_VERSION)
        self.assertEqual(self.manager.search('Pump')[0][0],0)
        self.assertEqual(self.manager.search('PUMP')[0][0],1)
        self.assertEqual(self.manager.search('pump')[0][0],2)
        self.assertEqual(hashes,[sha256(p.read_bytes()).hexdigest() for p in paths])
        self.assertEqual(len(self.manager.load()),3)

    def test_unknown_null_or_conflicting_versions_are_rejected(self):
        self.write_legacy()
        p=self.cfg.paths.bm25_corpus_path
        original=pickle.loads(p.read_bytes())
        for bad in ['future_v999',None,True]:
            p.write_bytes(pickle.dumps({**original,'tokenizer_version':bad}))
            with self.subTest(version=bad),self.assertRaisesRegex(ValueError,'tokenizer'):
                self.manager.load()
        p.write_bytes(pickle.dumps({**original,'tokenizer_version':CURRENT_TOKENIZER_VERSION}))
        with self.assertRaisesRegex(ValueError,'tokenizer'):
            self.manager.search('pump')

    def test_new_artifact_cannot_mislabel_legacy_tokens(self):
        texts=self.write_legacy()
        with self.assertRaisesRegex(ValueError,'tokenized corpus'):
            self.manager.save(chunk_ids=list(range(5)),tokenized_corpus=[bm25_tokenize(t,version=LEGACY_TOKENIZER_VERSION) for t in texts],corpus_texts=texts)

    def test_changed_tokens_cannot_masquerade_as_unversioned_legacy(self):
        texts=self.write_legacy()
        path=self.cfg.paths.bm25_corpus_path
        payload=pickle.loads(path.read_bytes())
        payload['tokenized_corpus']=[bm25_tokenize(text) for text in texts]
        path.write_bytes(pickle.dumps(payload))
        with self.assertRaisesRegex(ValueError,'tokenized corpus'):
            self.manager.load()

    def test_disabled_rebuild_preserves_existing_tokenizer_contract(self):
        texts=['PUMP thermal','sensor leakage','cold plate']
        self.manager.save(chunk_ids=[1,2,3],tokenized_corpus=[bm25_tokenize(t) for t in texts],corpus_texts=texts)
        before=self.cfg.paths.bm25_corpus_path.read_bytes()
        disabled=replace(self.cfg,bm25=replace(self.cfg.bm25,enabled=False))
        rebuild_bm25_index(disabled,None)
        self.assertEqual(self.cfg.paths.bm25_corpus_path.read_bytes(),before)
        self.assertFalse(self.manager.read_meta()['enabled'])
        self.assertEqual(self.manager.read_meta()['tokenizer_version'],CURRENT_TOKENIZER_VERSION)
        self.assertEqual(self.manager.search('pump')[0][0],1)

    def test_versioned_candidate_reload_and_diagnostic_query_agree(self):
        with synthetic_index_environment(self.root/'candidate-fixture',count=5) as (cfg,rows,_calls):
            build=candidate_builder.build_candidate_indexes(cfg,self.root/'candidates',version='lexical-v2',embed_batch=deterministic_vectors)
            self.assertEqual(build['bm25_tokenizer_version'],CURRENT_TOKENIZER_VERSION)
            payload,version=load_bm25_payload(build['bm25_path'],build['bm25_meta_path'])
            self.assertEqual(version,CURRENT_TOKENIZER_VERSION)
            self.assertEqual(payload['tokenized_corpus'],[bm25_tokenize(t) for t in payload['corpus_texts']])
            class Store:
                def __init__(self,*_): pass
                def load_chunk_catalog(self): return {}
            bundle=build_candidate_bundle(build)
            with patch('services.retrieval_service.indexing.diagnostics.read_only_store.SelectOnlyChunkStore',Store):
                evaluator=_BundleRuntime(cfg,bundle,embed_query=deterministic_vectors)
                self.assertEqual(evaluator.bm25_hits('THERMAL',topn=5),evaluator.bm25_hits('thermal',topn=5))
                self.assertEqual(evaluator.bm25_tokenizer_version,CURRENT_TOKENIZER_VERSION)
            runtime=DiagnosticRuntime(cfg,bundle,store=Store(),catalog={},embed_query=deterministic_vectors)
            self.assertEqual(runtime.bm25_tokenizer_version,CURRENT_TOKENIZER_VERSION)
            metadata=json.loads(Path(build['bm25_meta_path']).read_text())
            metadata['tokenizer_version']='unknown'
            Path(build['bm25_meta_path']).write_text(json.dumps(metadata),encoding='utf-8')
            result=index_validator.validate_candidate_index(cfg,build)
            self.assertFalse(result['passed'])
            self.assertIn('tokenizer',' '.join(result['errors']))
            with self.assertRaisesRegex(ValueError,'tokenizer'):
                DiagnosticRuntime(cfg,bundle,store=Store(),catalog={},embed_query=deterministic_vectors)


if __name__=='__main__':
    unittest.main(verbosity=2)
