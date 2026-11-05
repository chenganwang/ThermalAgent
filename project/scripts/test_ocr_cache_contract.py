"""OCR cache contract; real cache I/O, controlled image/OCR boundaries."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.retrieval_service.config import load_config
from services.ingest_service.ocr_pdf import ocr_pdf_pages
from services.ingest_service.chunking.page_text import PageText


class OCRCacheContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ocr-cache-contract-')
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.pdf = root / 'document.pdf'
        self.pdf.write_bytes(b'controlled PDF identity')
        self.engine = root / 'tesseract.exe'
        self.engine.write_bytes(b'controlled-engine-v1')
        tessdata = root / 'tessdata'
        tessdata.mkdir()
        (tessdata / 'eng.traineddata').write_bytes(b'controlled-trained-data-v1')
        self.cfg = load_config(root)
        self.cfg = replace(self.cfg, paths=replace(self.cfg.paths, data_dir=root / 'data'),
                           ocr=replace(self.cfg.ocr, tesseract_cmd=str(self.engine), lang='eng', tessdata_dir=str(tessdata)))
        self.addCleanup(patch.stopall)
        patch('services.ingest_service.ocr_pdf.extract_pdf_text_pages', return_value=[PageText(page=1, text='')]).start()
        self.render = patch('pdf2image.convert_from_path', return_value=[object()]).start()
        self.ocr = patch('pytesseract.image_to_string', side_effect=lambda *_args, **kwargs: f"{kwargs.get('lang')} result number {self.ocr.call_count}").start()
        patch('pytesseract.pytesseract.tesseract_cmd', str(self.engine)).start()

    def extract(self, cfg=None, force=False):
        return ocr_pdf_pages(self.pdf, cfg or self.cfg, force_ocr=force, max_pages=1)[0].text

    def test_identical_effective_contract_reuses_cache(self):
        first = self.extract()
        self.assertEqual(self.extract(), first)
        self.assertEqual(self.ocr.call_count, 1)
        self.assertEqual(self.render.call_count, 1)

    def test_language_change_executes_fresh_ocr(self):
        first = self.extract()
        changed = replace(self.cfg, ocr=replace(self.cfg.ocr, lang='chi_sim+eng'))
        self.assertNotEqual(self.extract(changed), first)
        self.assertEqual(self.ocr.call_count, 2)
        self.assertEqual(self.extract(), first)

    def test_render_resolution_change_executes_fresh_ocr(self):
        first = self.extract()
        changed = replace(self.cfg, ocr=replace(self.cfg.ocr, render_dpi=200))
        self.assertNotEqual(self.extract(changed), first)
        self.assertEqual(self.ocr.call_count, 2)
        self.assertEqual(self.render.call_args.kwargs['dpi'], 200)

    def test_engine_binary_change_executes_fresh_ocr(self):
        first = self.extract()
        self.engine.write_bytes(b'controlled-engine-v2')
        self.assertNotEqual(self.extract(), first)
        self.assertEqual(self.ocr.call_count, 2)

    def test_training_data_change_executes_fresh_ocr(self):
        first = self.extract()
        (Path(self.cfg.ocr.tessdata_dir) / 'eng.traineddata').write_bytes(b'controlled-trained-data-v2')
        self.assertNotEqual(self.extract(), first)
        self.assertEqual(self.ocr.call_count, 2)

    def test_cache_algorithm_version_change_executes_fresh_ocr(self):
        first = self.extract()
        with patch('services.ingest_service.ocr_cache.OCR_CACHE_VERSION', 'controlled-next-version'):
            self.assertNotEqual(self.extract(), first)
        self.assertEqual(self.ocr.call_count, 2)
        self.assertEqual(self.extract(), first)

    def test_force_ocr_refreshes_and_preserves_old_result(self):
        first = self.extract()
        refreshed = self.extract(force=True)
        self.assertNotEqual(refreshed, first)
        self.assertEqual(self.ocr.call_count, 2)
        self.assertEqual(self.extract(), refreshed)
        self.assertEqual(self.ocr.call_count, 2)
        stored = [p.read_text(encoding='utf-8') for p in self.cfg.paths.data_dir.rglob('*.txt')]
        self.assertIn(first, stored)
        self.assertIn(refreshed, stored)

    def test_unversioned_cache_is_preserved_but_not_used(self):
        old = self.cfg.paths.data_dir / 'ocr_cache' / sha256(self.pdf.read_bytes()).hexdigest() / 'page_0001.txt'
        old.parent.mkdir(parents=True)
        old.write_text('unverified historical OCR text', encoding='utf-8')
        self.assertNotEqual(self.extract(), old.read_text(encoding='utf-8'))
        self.assertEqual(self.ocr.call_count, 1)
        self.assertEqual(old.read_text(encoding='utf-8'), 'unverified historical OCR text')

    def test_preferred_usable_text_layer_never_invokes_ocr(self):
        good = 'Usable engineering text layer with a stable source page and sufficient content. ' * 3
        with patch('services.ingest_service.ocr_pdf.extract_pdf_text_pages', return_value=[PageText(page=1, text=good)]):
            self.assertEqual(self.extract(), good.strip())
        self.ocr.assert_not_called()
        self.render.assert_not_called()

    def test_explicit_force_ocr_retains_text_layer_bypass_semantics(self):
        good = 'Usable engineering text layer content. ' * 5
        with patch('services.ingest_service.ocr_pdf.extract_pdf_text_pages', return_value=[PageText(page=1, text=good)]) as extract:
            result = self.extract(force=True)
        self.assertNotEqual(result, good.strip())
        extract.assert_not_called()
        self.assertEqual(self.ocr.call_count, 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
