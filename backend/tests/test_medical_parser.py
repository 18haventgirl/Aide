import asyncio
import io
import importlib.util
import json
import os
import tempfile
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from core.database_core import DatabaseClient
from core.database_core.config import DatabaseConfig
from medical_parser.documents import extract_file, extract_text
from medical_parser.extractor import ground_result
from medical_parser.schema import FIELD_LABELS, MAX_BYTES, ParserError
from service.models.health_record import HealthRecord
from service.models.medical_document import MedicalDocument
from service.services.medical_document_service import MedicalDocumentService

TEXT = "示例医院 门诊病历\n姓名：张示例\n就诊日期：2026-10-06\n主诉：咳嗽3天。\n初步诊断：上呼吸道感染（待排）。\n过敏史：未详。"


def extraction():
    return ground_result({"document_type": "outpatient", "fields": {
        "patient_name": {"value": "张示例", "line_ids": ["p1-l2"]},
        "visit_date": {"value": "2026-10-06", "line_ids": ["p1-l3"]},
        "chief_complaint": {"value": "咳嗽3天。", "line_ids": ["p1-l4"]},
        "diagnosis": {"value": "上呼吸道感染（待排）。", "line_ids": ["p1-l5"]},
        "allergies": {"value": "未详。", "line_ids": ["p1-l6"]},
    }}, extract_text(TEXT))


class ExtractionTests(unittest.TestCase):
    def test_optional_ocr_image_and_scanned_pdf(self):
        try:
            from PIL import Image, ImageDraw, ImageFont
            import rapidocr_onnxruntime
            import pypdfium2
        except ImportError:
            self.skipTest('Install requirements-medical-parser-ocr.txt to verify local OCR')
        image = Image.new('RGB', (1100, 650), 'white')
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 38) if Path('C:/Windows/Fonts/arial.ttf').exists() else ImageFont.load_default(size=38)
        for index, text in enumerate(('Synthetic outpatient record', 'Name: Demo Patient', 'Chief complaint: cough for three days')):
            draw.text((40, 70 + index * 110), text, fill='black', font=font)
        for extension, format_name in [('png', 'PNG'), ('jpg', 'JPEG'), ('jpeg', 'JPEG'), ('pdf', 'PDF')]:
            with self.subTest(format=extension):
                buffer = io.BytesIO(); image.save(buffer, format=format_name)
                lines = extract_file(f'synthetic.{extension}', buffer.getvalue())
                self.assertIn('cough', ' '.join(line.text for line in lines))
                self.assertEqual({line.method for line in lines}, {'ocr'})

    def test_utf8_bom_uppercase_extension_and_text_limit(self):
        self.assertEqual(extract_file('病历.TXT', TEXT.encode('utf-8-sig'))[0].text, TEXT.splitlines()[0])
        with self.assertRaises(ParserError) as raised:
            extract_text('病历' * 20001)
        self.assertEqual(raised.exception.status_code, 413)

    def test_encrypted_pdf_rejected(self):
        from pypdf import PdfWriter
        writer = PdfWriter(); writer.add_blank_page(600, 800); writer.encrypt('synthetic-password')
        buffer = io.BytesIO(); writer.write(buffer)
        with self.assertRaisesRegex(ParserError, '密码保护'):
            extract_file('encrypted.pdf', buffer.getvalue())

    def test_basic_field_labels_removed_without_changing_clinical_qualifiers(self):
        result = ground_result({'document_type': 'outpatient', 'fields': {
            'patient_name': {'value': '姓名：张示例', 'line_ids': ['p1-l2']},
            'visit_date': {'value': '就诊日期：2026-10-06', 'line_ids': ['p1-l3']},
            'diagnosis': {'value': '初步诊断：上呼吸道感染（待排）。', 'line_ids': ['p1-l5']},
        }}, extract_text(TEXT))
        self.assertEqual(result['fields']['patient_name']['value'], '张示例')
        self.assertEqual(result['fields']['visit_date']['value'], '2026-10-06')
        self.assertEqual(result['fields']['diagnosis']['value'], '初步诊断：上呼吸道感染（待排）。')

    def test_native_text_and_docx_table_keep_source_order(self):
        self.assertEqual(extract_file("门诊.txt", TEXT.encode())[3].text, "主诉：咳嗽3天。")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            z.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>门诊病历示例</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>主诉：咳嗽3天</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>')
        lines = extract_file("门诊.docx", buffer.getvalue())
        self.assertEqual([line.text for line in lines], ["门诊病历示例", "主诉：咳嗽3天"])

    def test_file_limits_invalid_format_and_utf8(self):
        for name, data in [("x.txt", b"x" * (MAX_BYTES + 1)), ("x.exe", b"abcd"),
                           ("x.pdf", TEXT.encode()), ("x.txt", b"\xff\xff"), ("x.txt", b"")]:
            with self.subTest(name=name, size=len(data)), self.assertRaises(ParserError):
                extract_file(name, data)

    def test_image_in_docx_is_not_silently_omitted(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            z.writestr("word/media/image1.png", b"not-an-image")
        with self.assertRaisesRegex(ParserError, "含嵌入图片"):
            extract_file("x.docx", buffer.getvalue())

    def test_native_pdf_and_page_limits(self):
        from pypdf import PdfWriter
        from pypdf.generic import NameObject, DictionaryObject, DecodedStreamObject
        writer = PdfWriter()
        page = writer.add_blank_page(600, 800)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(b'BT /F1 12 Tf 50 700 Td (Outpatient record: Chief complaint cough for three days.) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(stream)
        buffer = io.BytesIO(); writer.write(buffer)
        self.assertIn('cough', extract_file('record.pdf', buffer.getvalue())[0].text)
        for _ in range(12): writer.add_blank_page(600, 800)
        buffer = io.BytesIO(); writer.write(buffer)
        with self.assertRaisesRegex(ParserError, "12 页"):
            extract_file('record.pdf', buffer.getvalue())

    def test_missing_and_uncertain_are_distinct(self):
        result = extraction()
        self.assertEqual(result['fields']['allergies']['value'], '未详。')
        self.assertEqual(result['fields']['past_history']['value'], '')
        self.assertEqual(result['fields']['past_history']['status'], 'missing')
        self.assertIn('待排', result['fields']['diagnosis']['value'])

    def test_hallucinated_forged_and_dropped_qualifiers_are_cleared(self):
        base = {"chief_complaint": {"value": "咳嗽3天。", "line_ids": ["p1-l4"]}}
        for field in [{"value": "肺炎", "line_ids": ["p1-l5"]},
                      {"value": "上呼吸道感染", "line_ids": ["p1-l5"]},
                      {"value": "上呼吸道感染（待排）。", "line_ids": ["p99-l1"]}]:
            result = ground_result({"document_type": "outpatient", "fields": {**base, "diagnosis": field}}, extract_text(TEXT))
            self.assertEqual(result['fields']['diagnosis']['value'], '')
            self.assertTrue(result['warnings'])


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        config = DatabaseConfig()
        config.db_type = 'sqlite'; config.sqlite_path = str(Path(self.tmp.name) / 'parser.db')
        self.db = DatabaseClient(config); self.assertTrue(self.db.initialize()); self.db.create_tables()
        self.service = MedicalDocumentService(self.db)
        self.draft = self.service._create(1, "合成样例.txt", "a" * 64, extraction())
        self.fields = {key: field['value'] for key, field in self.draft['result']['fields'].items()}

    def tearDown(self):
        self.db.engine.dispose(); self.tmp.cleanup()

    def test_draft_then_confirmation_preserves_original_and_corrections(self):
        with self.db.get_session() as session:
            self.assertEqual(session.query(HealthRecord).count(), 0)
        self.fields['patient_name'] = '核对后的示例'
        result = self.service.confirm(1, self.draft['id'], self.fields, date(2026, 10, 6))
        self.assertEqual(result['status'], 'confirmed')
        self.assertEqual(result['result']['fields']['patient_name']['value'], '张示例')
        self.assertEqual(result['reviewed']['fields']['patient_name'], '核对后的示例')
        with self.db.get_session() as session:
            record = session.query(HealthRecord).one()
            self.assertEqual(record.source, 'document')
            self.assertEqual(record.observed_at.date(), date(2026, 10, 6))
            self.assertEqual(record.details['人工修改字段'], ['姓名'])

    def test_other_user_cannot_read_confirm_or_delete(self):
        for operation in [lambda: self.service.get(2, self.draft['id']),
                          lambda: self.service.confirm(2, self.draft['id'], self.fields, date.today()),
                          lambda: self.service.delete(2, self.draft['id'])]:
            with self.assertRaises(ParserError) as raised: operation()
            self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(self.service.list(2), [])

    def test_concurrent_repeated_confirmations_create_one_health_record(self):
        second = MedicalDocumentService(self.db)
        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(service.confirm, 1, self.draft['id'], self.fields, date(2026, 10, 6)) for service in (self.service, second)]
            results = [future.result() for future in futures]
        self.assertEqual(results[0]['health_record_id'], results[1]['health_record_id'])
        with self.db.get_session() as session:
            self.assertEqual(session.query(HealthRecord).count(), 1)

    def test_delete_draft_removes_source_but_preserves_confirmed_health_record(self):
        self.service.confirm(1, self.draft['id'], self.fields, date.today())
        self.service.delete(1, self.draft['id'])
        with self.db.get_session() as session:
            self.assertEqual(session.query(MedicalDocument).count(), 0)
            self.assertEqual(session.query(HealthRecord).count(), 1)

    def test_model_failure_does_not_create_draft(self):
        with patch('service.services.medical_document_service.extract_record', AsyncMock(side_effect=ParserError('模型失败', 502))):
            with self.assertRaises(ParserError): asyncio.run(self.service.parse(1, 'x', text=TEXT))
        self.assertEqual(len(self.service.list(1)), 1)

    def test_capacity_limit_is_shared_across_agent_event_loops(self):
        self.service._slots.acquire(); self.service._slots.acquire()
        try:
            with ThreadPoolExecutor(2) as pool:
                def parse_from_loop():
                    with self.assertRaises(ParserError) as raised:
                        asyncio.run(self.service.parse(1, 'x', text=TEXT))
                    return raised.exception.status_code
                self.assertEqual(list(pool.map(lambda _: parse_from_loop(), range(2))), [429, 429])
        finally:
            self.service._slots.release(); self.service._slots.release()

    def test_api_parse_edit_confirm_and_ownership(self):
        from api.medical_document_api import medical_document_router
        from core.auth_core import get_current_user
        app = FastAPI(); app.include_router(medical_document_router, prefix='/api')
        app.dependency_overrides[get_current_user] = lambda: {'user_id': '1'}
        with patch('api.medical_document_api._service', return_value=self.service), patch('service.services.medical_document_service.extract_record', AsyncMock(return_value=extraction())), TestClient(app) as client:
            response = client.post('/api/medical-documents/parse-text', json={'text': TEXT})
            self.assertEqual(response.status_code, 200, response.text)
            doc = response.json()['data']
            saved = client.post(f"/api/medical-documents/{doc['id']}/confirm", json={'fields': self.fields, 'observed_date': '2026-10-06'})
            self.assertEqual(saved.status_code, 200, saved.text)
            app.dependency_overrides[get_current_user] = lambda: {'user_id': '2'}
            self.assertEqual(client.get(f"/api/medical-documents/{doc['id']}").status_code, 404)
            app.dependency_overrides.clear()
            self.assertIn(client.get('/api/medical-documents').status_code, (401, 403))

    def test_invalid_request_does_not_echo_patient_input(self):
        from api.medical_document_api import medical_document_router
        from core.auth_core import get_current_user
        app = FastAPI(); app.include_router(medical_document_router)
        app.dependency_overrides[get_current_user] = lambda: {'user_id': '1'}
        with TestClient(app) as client:
            response = client.post('/medical-documents/parse-text', json={'text': '患者秘密'})
            self.assertEqual(response.status_code, 422)
            self.assertNotIn('患者秘密', response.text)

    def test_file_upload_api_all_formats_and_confirmation(self):
        """Real decoders/OCR and raw HTTP upload; only the remote model is stubbed.

        Generate fixtures with create_medical_parser_fixtures.py and set
        MEDICAL_PARSER_TEST_FIXTURES. The live-browser matrix separately uses the real model.
        """
        directory = os.environ.get('MEDICAL_PARSER_TEST_FIXTURES')
        if not directory:
            self.skipTest('Set MEDICAL_PARSER_TEST_FIXTURES to the generated format matrix directory')
        directory = Path(directory)
        manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(len(manifest), 8)
        from api.medical_document_api import medical_document_router
        from core.auth_core import get_current_user
        app = FastAPI(); app.include_router(medical_document_router, prefix='/api')
        app.dependency_overrides[get_current_user] = lambda: {'user_id': '1'}

        async def grounded_model_stub(lines):
            fields = {}
            for key, value in [('patient_name', '周示例'), ('visit_date', '2026-10-09'),
                               ('diagnosis', '上呼吸道感染（待排）。'), ('chief_complaint', '咳嗽3天。'),
                               ('allergies', '青霉素过敏。'), ('past_history', '否认高血压病史。')]:
                evidence = next(line for line in lines if value.rstrip('。') in line.text)
                # Keep OCR punctuation exactly as read for the grounding check.
                actual = evidence.text.split('：', 1)[-1] if key in ('diagnosis', 'chief_complaint') else value
                fields[key] = {'value': actual, 'line_ids': [evidence.id]}
            return ground_result({'document_type': 'outpatient', 'fields': fields}, lines)

        with patch('api.medical_document_api._service', return_value=self.service), patch('service.services.medical_document_service.extract_record', side_effect=grounded_model_stub), TestClient(app) as client:
            for index, case in enumerate(manifest):
                with self.subTest(filename=case['filename']):
                    response = client.post('/api/medical-documents/parse-file', params={'filename': case['filename']},
                                           content=(directory / case['filename']).read_bytes(), headers={'Content-Type': 'application/octet-stream'})
                    self.assertEqual(response.status_code, 200, response.text)
                    doc = response.json()['data']
                    self.assertEqual(doc['status'], 'review')
                    self.assertEqual(doc['filename'], case['filename'])
                    self.assertEqual({line['method'] for line in doc['result']['source_lines']}, set(case['methods']))
                    with self.db.get_session() as session:
                        self.assertEqual(session.query(HealthRecord).count(), index)
                    fields = {key: field['value'] for key, field in doc['result']['fields'].items()}
                    self.assertEqual(fields['patient_name'], case['name'])
                    self.assertEqual(fields['visit_date'], case['date'])
                    self.assertIn(case['diagnosis_contains'], fields['diagnosis'])
                    self.assertIn(case['allergy_contains'], fields['allergies'])
                    self.assertIn('否认高血压', fields['past_history'])
                    self.assertEqual({line['page'] for line in doc['result']['source_lines']},
                                     {1, 2} if '-mixed.pdf' in case['filename'] else {1})
                    fields['patient_name'] = case['corrected_name']
                    payload = {'fields': fields, 'observed_date': case['date']}
                    endpoint = f"/api/medical-documents/{doc['id']}"
                    saved = client.post(endpoint + '/confirm', json=payload)
                    repeated = client.post(endpoint + '/confirm', json=payload)
                    self.assertEqual(saved.status_code, 200, saved.text)
                    self.assertEqual(repeated.status_code, 200, repeated.text)
                    self.assertEqual(saved.json()['data']['health_record_id'], repeated.json()['data']['health_record_id'])
                    reopened = client.get(endpoint).json()['data']
                    self.assertEqual(reopened['status'], 'confirmed')
                    self.assertEqual(reopened['reviewed']['fields']['patient_name'], case['corrected_name'])
                    self.assertEqual(reopened['reviewed']['observed_date'], case['date'])
                    self.assertEqual(reopened['result']['fields']['patient_name']['value'], case['name'])
            with self.db.get_session() as session:
                self.assertEqual(session.query(HealthRecord).count(), len(manifest))

    def test_file_upload_api_rejects_invalid_payloads_before_model(self):
        from api.medical_document_api import medical_document_router
        from core.auth_core import get_current_user
        app = FastAPI(); app.include_router(medical_document_router, prefix='/api')
        app.dependency_overrides[get_current_user] = lambda: {'user_id': '1'}
        cases = [('empty.txt', b'', 413), ('large.txt', b'x' * (MAX_BYTES + 1), 413),
                 ('bad.pdf', b'not a pdf', 422), ('bad.docx', b'not a zip', 422),
                 ('bad.txt', b'\xff\xff', 422), ('unsupported.doc', b'not supported', 415)]
        if importlib.util.find_spec('rapidocr_onnxruntime') and importlib.util.find_spec('PIL'):
            cases.extend((f'bad.{extension}', b'not an image', 422) for extension in ('png', 'jpg', 'jpeg'))
        with patch('api.medical_document_api._service', return_value=self.service), patch('service.services.medical_document_service.extract_record', AsyncMock()) as model, TestClient(app) as client:
            for name, payload, status in cases:
                with self.subTest(filename=name):
                    response = client.post('/api/medical-documents/parse-file', params={'filename': name}, content=payload)
                    self.assertEqual(response.status_code, status, response.text)
            model.assert_not_called()
        self.assertEqual(len(self.service.list(1)), 1)


if __name__ == '__main__': unittest.main()
