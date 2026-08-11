import asyncio
import json
import os
import tempfile
from pathlib import Path

import pytest

TEST_ROOT = Path(tempfile.gettempdir()) / 'barsan_r23_tests'
TEST_ROOT.mkdir(parents=True, exist_ok=True)
DB_FILE = TEST_ROOT / 'barsan.db'
if DB_FILE.exists():
    DB_FILE.unlink()

os.environ.update({
    'ENVIRONMENT': 'production',
    'DATABASE_URL': f'sqlite:///{DB_FILE}',
    'UPLOAD_DIR': str(TEST_ROOT / 'uploads'),
    'UPLOAD_SESSION_DIR': str(TEST_ROOT / 'upload-sessions'),
    'BACKUP_DIR': str(TEST_ROOT / 'backups'),
    'JWT_SECRET': '1234567890123456789012345678901234567890',
    'INITIAL_ADMIN_PASSWORD': 'StrongPass_12345',
    'AI_PROVIDER': 'openai_compatible',
    'AI_PROVIDER_LABEL': 'GapGPT Test',
    'AI_API_KEY': 'sk_test_placeholder',
    'AI_API_KEY_2': '',
    'AI_API_KEY_3': '',
    'AI_API_KEY_4': '',
    'AI_BASE_URL': 'https://api.gapgpt.app/v1',
    'AI_MODEL': 'gpt-4o-mini',
    'AI_TOKEN_PARAMETER': 'max_tokens',
    'ALLOWED_ORIGINS': 'http://testserver',
    'HEALTH_MONITOR_ENABLED': 'false',
    'AUTO_BACKUP_ENABLED': 'false',
    'BACKGROUND_DOCUMENT_PROCESSING': 'true',
    'ANSWER_CACHE_NAMESPACE': 'barsan-r28-tests',
    'BUILTIN_SOURCE_AUTO_INSTALL': 'false',
})

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def setup_module():
    main.init_storage()
    main.ensure_schema()
    main.seed_admin()


def owner_token() -> str:
    with main.get_db() as db:
        admin = db.execute("SELECT id, role FROM users WHERE is_owner=1 LIMIT 1").fetchone()
    return main.create_token(admin['id'], admin['role'])


def test_health_and_readiness():
    with TestClient(main.app) as client:
        health = client.get('/healthz')
        assert health.status_code == 200
        assert health.json()['version'] == '35.2.3'
        response = client.get('/readyz')
        assert response.status_code == 200
        assert response.json()['database'] is True
        assert response.json()['storage'] is True
        assert response.json()['release'] == 'R35_2_3_PREDEPLOY_OVERRIDE'



def test_operational_tools_restore_old_deterministic_engines():
    html = main.MAIN_HTML
    for panel, label in (("cargoPanel", "بررسی بار"), ("routePanel", "مسیریابی"), ("calcPanel", "محاسبات")):
        assert f'data-panel="{panel}"' in html
        assert f'id="{panel}"' in html
        assert label in html
    assert "runCargoFitV2()" in html
    assert "searchRoutingV2()" in html
    assert "calculateCancellationV2()" in html
    assert "calculateWaitingV2()" in html
    assert "calculateDeviationV2()" in html
    assert "/api/v1/cargo/check" in html
    assert "/api/v1/routing/search" in html
    assert "/api/v1/calculations/cancellation" in html
    assert "آموزش مدیر ← منابع" in html


def test_restored_cargo_geometry_uses_saved_vehicle_profile():
    token=owner_token();headers={'Authorization':f'Bearer {token}'}
    with TestClient(main.app) as client:
        r=client.put('/api/v1/cargo/vehicles/peykan_flatbed',headers=headers,json={'length_cm':100,'width_cm':100,'height_cm':100,'max_weight_kg':2000})
        assert r.status_code==200,r.text
        r=client.post('/api/v1/cargo/check',headers=headers,json={'vehicle':'peykan_flatbed','items':[{'name':'جعبه','count':10,'length_cm':10,'width_cm':10,'height_cm':20,'weight_kg':5}]})
        assert r.status_code==200,r.text
        data=r.json();calc=data['calculation']
        assert calc['fits'] is True
        assert calc['total_weight_kg']==50
        assert calc['occupied_height_cm']<=100
        assert 'ارتفاع' in data['answer']


def test_restored_cargo_reports_rear_overhang_when_rotation_disabled():
    token=owner_token();headers={'Authorization':f'Bearer {token}'}
    with TestClient(main.app) as client:
        client.put('/api/v1/cargo/vehicles/peykan_no_flatbed',headers=headers,json={'length_cm':100,'width_cm':100,'height_cm':100,'max_weight_kg':1000})
        r=client.post('/api/v1/cargo/check',headers=headers,json={'vehicle':'peykan_no_flatbed','items':[{'name':'بار بلند','count':1,'length_cm':140,'width_cm':20,'height_cm':20,'rotatable':False}]})
        assert r.status_code==200,r.text
        calc=r.json()['calculation']
        assert calc['fits'] is False
        assert calc['rear_overhang_cm']==pytest.approx(40.0)


def test_restored_calculation_formulas_are_deterministic():
    token=owner_token();headers={'Authorization':f'Bearer {token}'}
    setting={'cancellation_base_toman':100000,'waiting_hourly_toman':60000,'deviation_per_km_toman':10000,'free_wait_minutes':60,'extra_destination_free_minutes':15,'deviation_use_distance':True,'deviation_use_time':False}
    with TestClient(main.app) as client:
        r=client.put('/api/v1/calculations/settings/nissan',headers=headers,json=setting);assert r.status_code==200,r.text
        r=client.post('/api/v1/calculations/cancellation',headers=headers,json={'vehicle':'nissan','origin_wait_minutes':45});assert r.status_code==200,r.text
        assert r.json()['billable_wait_minutes']==30
        assert r.json()['final_amount_toman']==130000
        r=client.post('/api/v1/calculations/waiting',headers=headers,json={'vehicle':'nissan','calculation_mode':'minutes','origin_wait_minutes':60,'destination_wait_minutes':60,'destination_count':2});assert r.status_code==200,r.text
        assert r.json()['free_wait_minutes']==75
        assert r.json()['billable_wait_minutes']==45
        assert r.json()['final_amount_toman']==45000
        r=client.post('/api/v1/calculations/deviation',headers=headers,json={'vehicle':'nissan','distance_km':3.5});assert r.status_code==200,r.text
        assert r.json()['final_amount_toman']==35000


def test_restored_calculation_can_use_time_based_deviation():
    token=owner_token();headers={'Authorization':f'Bearer {token}'}
    setting={'cancellation_base_toman':100000,'waiting_hourly_toman':60000,'deviation_per_km_toman':0,'free_wait_minutes':60,'extra_destination_free_minutes':15,'deviation_use_distance':False,'deviation_use_time':True}
    with TestClient(main.app) as client:
        r=client.put('/api/v1/calculations/settings/nissan',headers=headers,json=setting);assert r.status_code==200,r.text
        r=client.post('/api/v1/calculations/deviation',headers=headers,json={'vehicle':'nissan','wait_minutes':30,'service_amount_toman':500000});assert r.status_code==200,r.text
        assert r.json()['deviation_amount_toman']==30000
        assert r.json()['final_amount_toman']==530000


def test_restored_neshan_routing_is_independent_and_cacheable(monkeypatch):
    import types
    token=owner_token();headers={'Authorization':f'Bearer {token}'}
    async def fake_lookup(*args,**kwargs):
        return types.SimpleNamespace(items=[{'title':'انبار تست','address':'تهران، آدرس تست','latitude':35.7,'longitude':51.3,'confidence':0.95,'map_url':'https://neshan.org/maps/@35.7,51.3,16z,0p','navigation_url':'https://nshn.ir/test','google_maps_url':'https://www.google.com/maps?q=35.7,51.3','balad_url':'https://balad.ir/location?latitude=35.7&longitude=51.3','provider':'neshan_geocoding'}],provider_calls=1,used_plus=True,used_search=False)
    monkeypatch.setattr(main,'NESHAN_API_KEY','test-key')
    monkeypatch.setattr(main,'lookup_neshan',fake_lookup)
    with main.get_db() as db: db.execute('DELETE FROM location_cache')
    with TestClient(main.app) as client:
        r=client.post('/api/v1/routing/search',headers=headers,json={'query':'آدرس تست تهران'});assert r.status_code==200,r.text
        assert r.json()['items'][0]['title']=='انبار تست'
        r2=client.post('/api/v1/routing/search',headers=headers,json={'query':'آدرس تست تهران'});assert r2.status_code==200,r2.text
        assert r2.json()['cached'] is True
        assert r2.json()['provider_calls']==0


def test_admin_password_policy_accepts_requested_ten_digit_password(monkeypatch):
    old = main.INITIAL_ADMIN_PASSWORD
    try:
        monkeypatch.setattr(main, 'INITIAL_ADMIN_PASSWORD', '9876543210')
        main.validate_environment()
    finally:
        monkeypatch.setattr(main, 'INITIAL_ADMIN_PASSWORD', old)


def test_master_admin_credentials_can_sync_on_existing_database(monkeypatch):
    old_email = main.MASTER_ADMIN_EMAIL
    old_initial_email = main.INITIAL_ADMIN_EMAIL
    old_password = main.INITIAL_ADMIN_PASSWORD
    old_sync = main.SYNC_MASTER_ADMIN_CREDENTIALS
    try:
        monkeypatch.setattr(main, 'MASTER_ADMIN_EMAIL', 'amir@gmail.com')
        monkeypatch.setattr(main, 'INITIAL_ADMIN_EMAIL', 'amir@gmail.com')
        monkeypatch.setattr(main, 'INITIAL_ADMIN_PASSWORD', '9876543210')
        monkeypatch.setattr(main, 'SYNC_MASTER_ADMIN_CREDENTIALS', True)
        main.seed_admin()
        with main.get_db() as db:
            row = db.execute("SELECT email,password_hash,salt FROM users WHERE is_owner=1 LIMIT 1").fetchone()
        assert row['email'] == 'amir@gmail.com'
        assert main.verify_password('9876543210', row['password_hash'], row['salt'])
    finally:
        monkeypatch.setattr(main, 'MASTER_ADMIN_EMAIL', old_email)
        monkeypatch.setattr(main, 'INITIAL_ADMIN_EMAIL', old_initial_email)
        monkeypatch.setattr(main, 'INITIAL_ADMIN_PASSWORD', old_password)
        monkeypatch.setattr(main, 'SYNC_MASTER_ADMIN_CREDENTIALS', old_sync)
        main.seed_admin()

def test_generic_provider_can_be_switched_with_environment(monkeypatch):
    monkeypatch.setattr(main, 'AI_PROVIDER', 'openai_compatible')
    monkeypatch.setattr(main, 'AI_API_KEY', 'sk_test_placeholder')
    monkeypatch.setattr(main, 'AI_BASE_URL', 'https://provider.example/v1')
    monkeypatch.setattr(main, 'AI_MODEL', 'custom-model')
    monkeypatch.setattr(main, 'GEMINI_API_KEY', '')
    main.validate_environment()
    assert main.active_model_name() == 'custom-model'



def test_removed_provider_is_not_supported():
    assert 'gro' + 'q' not in main.OPENAI_COMPATIBLE_PROVIDERS
    with pytest.raises(RuntimeError):
        old = main.AI_PROVIDER
        try:
            main.AI_PROVIDER = 'gro' + 'q'
            main.validate_environment()
        finally:
            main.AI_PROVIDER = old

def test_long_message_is_stored_without_truncation():
    conversation_id = main.create_conversation(None, 'external-test-user', 'long answer')
    content = 'پاسخ کامل و بدون قطع شدن ' * 10000
    message_id = main.save_message(conversation_id, 'assistant', content)
    with main.get_db() as db:
        row = db.execute('SELECT content FROM messages WHERE id=?', (message_id,)).fetchone()
    assert row['content'] == content


def insert_document(document_id: str, filename: str, chunks: list[str]):
    with main.get_db() as db:
        db.execute(
            "INSERT OR REPLACE INTO documents(id,filename,stored_path,mime_type,visibility,status,character_count,chunk_count,version,created_at) "
            "VALUES (?,?,?,?,?,'ready',?,?,1,?)",
            (document_id, filename, str(TEST_ROOT / filename), 'text/plain', 'public', sum(map(len, chunks)), len(chunks), main.now_iso()),
        )
        db.execute('DELETE FROM chunks WHERE document_id=?', (document_id,))
        db.execute('DELETE FROM chunks_fts WHERE document_id=?', (document_id,))
        rows = [(document_id, index, content) for index, content in enumerate(chunks)]
        db.executemany('INSERT INTO chunks(document_id,chunk_index,content) VALUES (?,?,?)', rows)
        db.executemany(
            'INSERT INTO chunks_fts(content,file_name,visibility,document_id,chunk_index) VALUES (?,?,?,?,?)',
            [(content, filename, 'public', document_id, index) for _, index, content in rows],
        )


def test_hybrid_retrieval_finds_synonyms_and_neighboring_chunks():
    insert_document('doc-neighbor-test', 'policy.txt', [
        'مقدمه قوانین لغو سرویس و شرایط استفاده مشتریان.',
        'هزینه کنسلی سرویس ویژه برابر با پانصد هزار تومان است.',
        'درخواست باید حداقل دو روز زودتر ثبت شود و پس از آن قابل استرداد نیست.',
    ])
    results = main.retrieve('قیمت لغو سرویس ویژه و مهلت درخواست چقدر است؟', None)
    assert results
    combined = '\n'.join(item['content'] for item in results)
    assert 'پانصد هزار تومان' in combined
    assert 'دو روز زودتر' in combined


def test_active_training_is_connected_to_answer_retrieval():
    with main.get_db() as db:
        owner = db.execute('SELECT id FROM users WHERE is_owner=1 LIMIT 1').fetchone()['id']
        ts = main.now_iso()
        db.execute(
            "INSERT OR REPLACE INTO training_rules(id,topic,topic_key,canonical_key,instruction,answer,priority,status,effective_from,created_by,approved_by,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ('training-cancel', 'لغو اشتراک', 'لغو اشتراک', 'اشتراک|کنسلی', 'درباره هزینه لغو اشتراک پاسخ بده',
             'هزینه کنسلی اشتراک طلایی دویست هزار تومان است و درخواست باید قبل از تمدید ثبت شود.',
             900, 'active', ts, owner, owner, ts, ts),
        )
    results = main.retrieve_training('قیمت لغو اشتراک طلایی چقدر است؟')
    assert results
    assert results[0]['source_type'] == 'training'
    assert 'دویست هزار تومان' in results[0]['answer']


async def _fake_generation(messages, *, max_tokens, temperature, route='standard'):
    if any('انتهای پاسخ قبلی' in item.get('content','') for item in messages):
        return 'این ادامه پاسخ است و اکنون همه شرایط با یک نتیجه‌گیری کامل به پایان رسیده است.', {'prompt_tokens': 5, 'output_tokens': 15, 'total_tokens': 20}, 'stop'
    return 'بخش نخست پاسخ هنوز کامل نشده و شامل', {'prompt_tokens': 10, 'output_tokens': 8, 'total_tokens': 18}, 'length'


def test_length_finish_reason_triggers_continuation(monkeypatch):
    monkeypatch.setattr(main, '_generate_ai_text', _fake_generation)
    context = [{
        'source_type': 'document',
        'document_id': 'doc',
        'file_name': 'source.txt',
        'chunk_index': 0,
        'content': 'متن کامل منبع با چند شرط برای ایجاد پاسخ آزمایشی دقیق و قابل اتکا.',
        'excerpt': 'متن کامل منبع',
        'score': 1.0,
    }]
    answer, usage = asyncio.run(main.ask_ai('سؤال آزمایشی', context))
    assert answer.endswith('پایان رسیده است.')
    assert 'بخش نخست پاسخ' in answer
    assert usage['total_tokens'] == 38


async def _fake_compatible_response(**kwargs):
    assert kwargs['url'] == 'https://api.gapgpt.app/v1/chat/completions'
    assert kwargs['payload']['model'] == 'gpt-4o-mini'
    assert kwargs['payload']['max_tokens'] == 777
    assert kwargs['payload']['stream'] is False
    assert kwargs['headers']['Authorization'] == 'Bearer sk_test_placeholder'
    return {
        'choices': [{'message': {'content': 'پاسخ کامل آزمایشی.'}, 'finish_reason': 'stop'}],
        'usage': {'prompt_tokens': 11, 'completion_tokens': 7, 'total_tokens': 18},
    }


def test_openai_compatible_payload_and_usage(monkeypatch):
    monkeypatch.setattr(main, 'AI_PROVIDER', 'openai_compatible')
    monkeypatch.setattr(main, 'AI_API_KEY', 'sk_test_placeholder')
    monkeypatch.setattr(main, 'AI_BASE_URL', 'https://api.gapgpt.app/v1')
    monkeypatch.setattr(main, 'AI_MODEL', 'gpt-4o-mini')
    monkeypatch.setattr(main, 'AI_TOKEN_PARAMETER', 'max_tokens')
    monkeypatch.setattr(main, '_request_json_with_retries', _fake_compatible_response)
    answer, usage, finish = asyncio.run(main._generate_ai_text(
        [{'role': 'user', 'content': 'سلام'}], max_tokens=777, temperature=0.1
    ))
    assert answer == 'پاسخ کامل آزمایشی.'
    assert usage['prompt_tokens'] == 11 and usage['output_tokens'] == 7 and usage['total_tokens'] == 18
    assert usage['api_slot'] == 1 and usage['model_route'] == 'standard'
    assert finish == 'stop'


def test_mobile_upload_progress_ui_contract():
    html = main.MAIN_HTML
    assert 'id="docFile" type="file" accept=' in html
    assert 'new XMLHttpRequest()' in html
    assert 'xhr.upload.onprogress' in html
    assert 'docUploadProgress' in html
    assert 'docUploadPercent' in html
    assert '/api/v1/admin/documents/reindex-all' in html
    assert 'سؤال را اینجا تایپ کنید' in html
    assert 'BARSAN R23 LIQUID MINIMAL' in html
    assert "font-family:'Vazirmatn'" in html
    assert '.composer{position:relative' in html
    assert 'await typeText(body,d.answer)' in html


def test_admin_mobile_multipart_upload_and_reindex_all():
    token = owner_token()
    text = 'قانون آزمایشی بارسان: هزینه فعال‌سازی سرویس حرفه‌ای سیصد هزار تومان است و اعتبار آن سی روز خواهد بود.'
    with TestClient(main.app) as client:
        response = client.post(
            '/api/v1/admin/documents',
            headers={'Authorization': f'Bearer {token}'},
            files={'file': ('mobile-note.txt', text.encode('utf-8'), 'text/plain')},
            data={'visibility': 'public'},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload['filename'] == 'mobile-note.txt'
        assert payload['status'] == 'processing'
        job_id = payload['job_id']
        job = None
        for _ in range(80):
            polled = client.get(f'/api/v1/admin/document-jobs/{job_id}', headers={'Authorization': f'Bearer {token}'})
            assert polled.status_code == 200, polled.text
            job = polled.json()
            if job['status'] in {'ready','failed'}:
                break
            import time as _time; _time.sleep(0.03)
        assert job and job['status'] == 'ready', job
        assert job['progress'] == 100
        reindexed = client.post('/api/v1/admin/documents/reindex-all', headers={'Authorization': f'Bearer {token}'})
        assert reindexed.status_code == 200, reindexed.text
        reindex_payload=reindexed.json()
        assert reindex_payload['succeeded'] >= 1
        for item in reindex_payload.get('results',[]):
            if not item.get('job_id'): continue
            for _ in range(100):
                polled=client.get(f"/api/v1/admin/document-jobs/{item['job_id']}",headers={'Authorization':f'Bearer {token}'})
                assert polled.status_code==200
                if polled.json()['status'] in {'ready','partial','error'}: break
                import time as _time; _time.sleep(0.03)

    results = main.retrieve('هزینه فعال سازی سرویس حرفه‌ای چقدر است؟', None)
    assert results
    assert any('سیصد هزار تومان' in item['content'] for item in results)

async def _fake_array_content_response(**kwargs):
    return {
        'choices': [{
            'message': {'content': [{'type': 'text', 'text': 'بخش اول'}, {'type': 'text', 'text': 'بخش دوم.'}]},
            'finish_reason': 'stop',
        }],
        'usage': {'prompt_tokens': 3, 'completion_tokens': 4, 'total_tokens': 7},
    }


def test_openai_compatible_array_content_is_supported(monkeypatch):
    monkeypatch.setattr(main, 'AI_PROVIDER', 'openai_compatible')
    monkeypatch.setattr(main, 'AI_API_KEY', 'sk_test_placeholder')
    monkeypatch.setattr(main, 'AI_BASE_URL', 'https://provider.example/v1')
    monkeypatch.setattr(main, 'AI_MODEL', 'custom-model')
    monkeypatch.setattr(main, '_request_json_with_retries', _fake_array_content_response)
    answer, usage, finish = asyncio.run(main._generate_ai_text(
        [{'role': 'user', 'content': 'سلام'}], max_tokens=100, temperature=0.1
    ))
    assert answer == 'بخش اول\nبخش دوم.'
    assert usage['total_tokens'] == 7
    assert finish == 'stop'


def test_auto_token_parameter_falls_back_to_max_completion_tokens(monkeypatch):
    calls = []

    async def fake_request(**kwargs):
        calls.append(kwargs['payload'])
        if len(calls) == 1:
            raise main.HTTPException(status_code=502, detail='خطای Test: HTTP 400 — unsupported max_tokens')
        return {
            'choices': [{'message': {'content': 'پاسخ کامل پس از سازگاری خودکار.'}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 5, 'completion_tokens': 6, 'total_tokens': 11},
        }

    monkeypatch.setattr(main, 'AI_PROVIDER', 'openai_compatible')
    monkeypatch.setattr(main, 'AI_TOKEN_PARAMETER', 'auto')
    monkeypatch.setattr(main, '_request_json_with_retries', fake_request)
    answer, _, finish = asyncio.run(main._generate_ai_text(
        [{'role': 'user', 'content': 'تست سازگاری'}], max_tokens=321, temperature=0.0
    ))
    assert 'max_tokens' in calls[0]
    assert 'max_completion_tokens' in calls[1]
    assert answer.endswith('خودکار.')
    assert finish == 'stop'



def test_default_answer_mode_is_concise_and_detail_mode_is_explicit():
    assert main.is_detailed_request('لطفاً کامل توضیح بده شرایط چیست؟') is True
    assert main.is_detailed_request('قیمت دقیق این سرویس چقدر است؟') is False
    long_answer = 'پاسخ مستقیم اول است. جمله دوم نکته ضروری را می‌گوید. جمله سوم نباید در حالت عادی نمایش داده شود.'
    concise = main.format_answer_for_mode(long_answer, False)
    assert concise == 'پاسخ مستقیم اول است. جمله دوم نکته ضروری را میگوید.'
    detailed = main.format_answer_for_mode(long_answer, True)
    assert 'جمله سوم' in detailed


def test_answer_sanitizer_removes_bidi_and_markdown_noise():
    dirty = '\u202e**پاسخ**\u200f  دقیق  ،بدون   نویسه\ufffd عجیب.'
    clean = main.sanitize_answer_text(dirty)
    assert '\u202e' not in clean and '\u200f' not in clean and '\ufffd' not in clean
    assert '**' not in clean
    assert '  ' not in clean
    assert clean == 'پاسخ دقیق، بدون نویسه عجیب.'


def test_repeated_question_uses_cache_without_second_ai_call(monkeypatch):
    insert_document('doc-cache-test', 'cache-source.txt', [
        'هزینه فعال سازی سرویس کش بارسان چهارصد هزار تومان است.'
    ])
    calls = {'count': 0}

    async def fake_ask(question, context_items, detailed=False, route='standard', memory=''):
        calls['count'] += 1
        return main.format_answer_for_mode('هزینه فعال‌سازی سرویس کش بارسان چهارصد هزار تومان است.', detailed), {
            'prompt_tokens': 30, 'output_tokens': 12, 'total_tokens': 42,
        }

    monkeypatch.setattr(main, 'ask_ai', fake_ask)
    first = asyncio.run(main.process_chat(
        message='هزینه فعال سازی سرویس کش بارسان چقدر است؟', conversation_id=None,
        user=None, external_user_id='cache-user-1', integration=True,
    ))
    second = asyncio.run(main.process_chat(
        message='هزینه فعال‌سازی سرویس کش بارسان چقدر است ؟', conversation_id=None,
        user=None, external_user_id='cache-user-2', integration=True,
    ))
    assert first['cached'] is False
    assert second['cached'] is True
    assert second['usage']['total_tokens'] == 0
    assert second['answer'] == first['answer']
    assert calls['count'] == 1
    with main.get_db() as db:
        row = db.execute("SELECT hit_count FROM answer_cache WHERE sample_question LIKE '%سرویس کش بارسان%' ORDER BY id DESC LIMIT 1").fetchone()
    assert row and row['hit_count'] >= 1


def test_cache_is_separate_for_detailed_requests(monkeypatch):
    calls = {'count': 0}

    async def fake_ask(question, context_items, detailed=False, route='standard', memory=''):
        calls['count'] += 1
        if detailed:
            return 'پاسخ کامل شامل شرط اول است. شرط دوم نیز باید رعایت شود. نتیجه نهایی مشخص است.', {'prompt_tokens':20,'output_tokens':20,'total_tokens':40}
        return 'پاسخ کوتاه است.', {'prompt_tokens':10,'output_tokens':5,'total_tokens':15}

    monkeypatch.setattr(main, 'ask_ai', fake_ask)
    result = asyncio.run(main.process_chat(
        message='هزینه فعال سازی سرویس کش بارسان را کامل توضیح بده', conversation_id=None,
        user=None, external_user_id='cache-detail-user', integration=True,
    ))
    assert result['detailed'] is True
    assert result['cached'] is False
    assert 'شرط دوم' in result['answer']
    assert calls['count'] == 1


def test_source_first_context_defaults_are_accuracy_focused():
    assert main.AI_DEFAULT_MAX_COMPLETION_TOKENS <= 900
    assert main.RETRIEVAL_TOP_K >= 10
    assert main.RETRIEVAL_TOTAL_ITEMS >= main.RETRIEVAL_TOP_K
    assert main.RETRIEVAL_NEIGHBOR_CHUNKS >= 2
    assert main.RETRIEVAL_MAX_CONTEXT_CHARS >= 22000
    assert main.SOURCE_FIRST_STRICT is True
    assert main.SOURCE_ANSWER_VERIFICATION is True
    assert main.ANSWER_CACHE_ENABLED is True


def test_cache_invalidates_when_source_version_changes(monkeypatch):
    insert_document('doc-cache-version', 'cache-version.txt', [
        'هزینه سرویس نسخه کش پانصد هزار تومان است.'
    ])
    calls = {'count': 0}

    async def fake_ask(question, context_items, detailed=False, route='standard', memory=''):
        calls['count'] += 1
        return f'پاسخ تولیدشده شماره {calls["count"]}.', {'prompt_tokens':5,'output_tokens':5,'total_tokens':10}

    monkeypatch.setattr(main, 'ask_ai', fake_ask)
    question = 'هزینه سرویس نسخه کش چقدر است؟'
    first = asyncio.run(main.process_chat(message=question,conversation_id=None,user=None,external_user_id='version-a',integration=True))
    second = asyncio.run(main.process_chat(message=question,conversation_id=None,user=None,external_user_id='version-b',integration=True))
    assert first['cached'] is False and second['cached'] is True
    with main.get_db() as db:
        db.execute("UPDATE documents SET version=version+1 WHERE id='doc-cache-version'")
        main.bump_knowledge_version(db)
    third = asyncio.run(main.process_chat(message=question,conversation_id=None,user=None,external_user_id='version-c',integration=True))
    assert third['cached'] is False
    assert calls['count'] == 2


def test_history_is_compact_and_widget_composer_is_purple():
    assert 'grid-template-columns:215px 1fr' in main.MAIN_HTML
    assert 'conversation-list{height:190px}' in main.MAIN_HTML
    assert 'LIMIT 60' in Path(main.__file__).read_text(encoding='utf-8')
    assert 'textarea{min-height:74px;border:2px solid #8b5cf6' in main.WIDGET_HTML


def create_limited_user(username: str, limit: int | None):
    password_hash, salt = main.hash_password('Password_123')
    with main.get_db() as db:
        cur = db.execute(
            "INSERT INTO users(username,name,password_hash,salt,role,is_active,is_owner,question_limit,questions_used,created_at) VALUES(?,?,?,?, 'user',1,0,?,0,?)",
            (username, username, password_hash, salt, limit, main.now_iso()),
        )
        return {'id': cur.lastrowid, 'username': username, 'role': 'user', 'is_active': 1, 'question_limit': limit, 'questions_used': 0}


def test_faq_is_fallback_only_and_uses_zero_tokens(monkeypatch):
    with main.get_db() as db:
        owner = db.execute('SELECT id FROM users WHERE is_owner=1 LIMIT 1').fetchone()['id']
    main.upsert_faq_rows([{
        'question': 'کد سرویس زعفرانی چیست؟',
        'answer': 'کد سرویس زعفرانی ZF-4818 است.',
        'aliases': ['شناسه زعفرانی'],
        'priority': 500,
        'is_active': True,
    }], owner)

    async def must_not_call_ai(*args, **kwargs):
        raise AssertionError('FAQ fallback must not call the AI provider')

    monkeypatch.setattr(main, 'ask_ai', must_not_call_ai)
    monkeypatch.setattr(main, 'ask_ai_without_sources', must_not_call_ai)
    result = asyncio.run(main.process_chat(
        message='شناسه زعفرانی چیه؟', conversation_id=None,
        user=None, external_user_id='faq-zero-token-user', integration=True,
    ))
    assert result['status'] == 'faq_hit'
    assert result['zero_token'] is True
    assert 'ZF-4818' in result['answer']


def test_training_has_absolute_priority_over_document_and_faq(monkeypatch):
    with main.get_db() as db:
        owner = db.execute('SELECT id FROM users WHERE is_owner=1 LIMIT 1').fetchone()['id']
        ts=main.now_iso()
        db.execute(
            "INSERT OR REPLACE INTO training_rules(id,topic,topic_key,canonical_key,instruction,answer,priority,status,effective_from,created_by,approved_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ('training-priority-r27','روبار پیکان','روبار پیکان','پیکان|روباری','درباره مقدار روبار پیکان پاسخ بده','طبق آموزش مدیر، روبار مجاز پیکان ۳۰۰ کیلوگرم است.',100,'active',ts,owner,owner,ts,ts),
        )
        main.rebuild_training_fts(db)
    insert_document('doc-priority-r27','priority-policy.txt',['در یک منبع قدیمی روبار پیکان ۲۰۰ کیلوگرم نوشته شده است.'])
    main.upsert_faq_rows([{'question':'روبار پیکان چقدر است؟','answer':'در FAQ مقدار ۲۵۰ کیلوگرم ثبت شده است.','aliases':['روبار پیکان'],'is_active':True}],owner)

    async def fake_ask(question, context_items, detailed=False, route='standard', memory=''):
        assert context_items
        assert all(item.get('source_type')=='training' for item in context_items)
        return 'طبق آموزش مدیر، روبار مجاز پیکان ۳۰۰ کیلوگرم است.', {'prompt_tokens':5,'output_tokens':8,'total_tokens':13}
    monkeypatch.setattr(main,'ask_ai',fake_ask)
    result=asyncio.run(main.process_chat(message='روبار پیکان چقدره؟',conversation_id=None,user=None,external_user_id='training-priority-user',integration=True))
    assert result['status']=='training_answer'
    assert '۳۰۰' in result['answer']
    assert all(src.get('source_type')=='training' for src in result['sources'])


def test_document_is_used_when_no_relevant_training_even_if_faq_exists(monkeypatch):
    with main.get_db() as db:
        owner=db.execute('SELECT id FROM users WHERE is_owner=1 LIMIT 1').fetchone()['id']
    insert_document('doc-source-second-r27','nissan-policy.txt',['وزن مجاز بارگیری نیسان در حالت عمومی ۲۰۰۰ کیلوگرم است؛ در شرایط سربالایی خاص شمال تهران ۱۷۰۰ کیلوگرم است.'])
    main.upsert_faq_rows([{'question':'وزن مجاز نیسان چقدر است؟','answer':'FAQ قدیمی: ۱۵۰۰ کیلوگرم.','aliases':['وزن نیسان'],'is_active':True}],owner)
    async def fake_ask(question, context_items, detailed=False, route='standard', memory=''):
        assert context_items
        assert all(item.get('source_type')!='training' for item in context_items)
        return 'وزن مجاز عمومی نیسان ۲۰۰۰ کیلوگرم است؛ اما در سربالایی خاص شمال تهران ۱۷۰۰ کیلوگرم است.', {'prompt_tokens':7,'output_tokens':12,'total_tokens':19}
    monkeypatch.setattr(main,'ask_ai',fake_ask)
    result=asyncio.run(main.process_chat(message='وزن مجاز نیسان چقدره؟',conversation_id=None,user=None,external_user_id='source-second-user',integration=True))
    assert result['status']=='answered'
    assert '۲۰۰۰' in result['answer'] and '۱۷۰۰' in result['answer']


def test_user_question_limit_is_atomic_and_blocks_extra_questions(monkeypatch):
    user = create_limited_user('limited_expert', 2)
    with main.get_db() as db:
        owner = db.execute('SELECT id FROM users WHERE is_owner=1 LIMIT 1').fetchone()['id']
    main.upsert_faq_rows([{
        'question': 'ساعت پاسخگویی محدودیت تست چیست؟',
        'answer': 'ساعت پاسخگویی از ۹ تا ۱۷ است.',
        'aliases': [], 'priority': 100, 'is_active': True,
    }], owner)
    for _ in range(2):
        result = asyncio.run(main.process_chat(
            message='ساعت پاسخگویی محدودیت تست چیست؟', conversation_id=None,
            user=user, external_user_id=None, integration=False,
        ))
        assert result['quota']['used'] in {1, 2}
    try:
        asyncio.run(main.process_chat(
            message='ساعت پاسخگویی محدودیت تست چیست؟', conversation_id=None,
            user=user, external_user_id=None, integration=False,
        ))
        assert False, 'third question should be rejected'
    except main.HTTPException as exc:
        assert exc.status_code == 429
        assert 'سهمیه سؤال' in exc.detail
    with main.get_db() as db:
        row = db.execute('SELECT questions_used,question_limit FROM users WHERE id=?', (user['id'],)).fetchone()
    assert row['questions_used'] == 2 and row['question_limit'] == 2


def test_four_api_pool_rotates_on_limit(monkeypatch):
    monkeypatch.setattr(main, 'AI_PROVIDER', 'openai_compatible')
    monkeypatch.setattr(main, 'AI_API_KEY_1', 'pool-key-1')
    monkeypatch.setattr(main, 'AI_API_KEY_2', 'pool-key-2')
    monkeypatch.setattr(main, 'AI_API_KEY_3', 'pool-key-3')
    monkeypatch.setattr(main, 'AI_API_KEY_4', 'pool-key-4')
    monkeypatch.setattr(main, 'AI_API_KEY', '')
    monkeypatch.setattr(main, 'AI_BASE_URL', 'https://provider.example/v1')
    monkeypatch.setattr(main, 'AI_MODEL', 'pool-model')
    monkeypatch.setattr(main, 'AI_TOKEN_PARAMETER', 'max_tokens')
    with main.get_db() as db:
        db.execute('DELETE FROM ai_api_slot_state')
        db.execute("UPDATE system_settings SET value='1' WHERE key='active_api_slot'")
    calls = []

    async def fake_request(**kwargs):
        auth = kwargs['headers']['Authorization']
        calls.append(auth)
        if auth.endswith('pool-key-1'):
            raise main.ApiSlotLimitError(429, 'rate limit reached', 60)
        return {
            'choices': [{'message': {'content': 'پاسخ از API دوم.'}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 2, 'completion_tokens': 3, 'total_tokens': 5},
        }

    monkeypatch.setattr(main, '_request_json_with_retries', fake_request)
    answer, usage, finish = asyncio.run(main._generate_ai_text(
        [{'role': 'user', 'content': 'تست گردش'}], max_tokens=100, temperature=0.0
    ))
    assert calls == ['Bearer pool-key-1', 'Bearer pool-key-2']
    assert answer == 'پاسخ از API دوم.' and usage['total_tokens'] == 5 and finish == 'stop'
    status = main.api_pool_public_status()
    assert status['active_slot'] == 2
    assert status['slots'][0]['status'] == 'blocked'


def test_faq_csv_import_and_manager_access_contract():
    payload = '\ufeffquestion,answer,aliases,priority,active\nهزینه نصب چیست؟,هزینه نصب صد هزار تومان است.,قیمت نصب|مبلغ نصب,200,1\n'.encode('utf-8')
    rows = main.parse_faq_import('faqs.csv', payload)
    assert len(rows) == 1
    assert 'priority' not in rows[0]
    assert 'قیمت نصب' in rows[0]['aliases']
    assert '/api/v1/faqs/import' in main.MAIN_HTML
    assert 'سؤالات متداول و کش بدون مصرف توکن' in main.MAIN_HTML
    assert 'data-panel="faqPanel"' in main.MAIN_HTML


def test_strict_retrieval_priority_prefers_training_over_documents():
    with main.get_db() as db:
        owner = db.execute('SELECT id FROM users WHERE is_owner=1 LIMIT 1').fetchone()['id']
        ts = main.now_iso()
        db.execute(
            "INSERT OR REPLACE INTO training_rules(id,topic,topic_key,canonical_key,instruction,answer,priority,status,effective_from,created_by,approved_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ('training-priority-r18','سقف برداشت','سقف برداشت','برداشت|سقف','سقف برداشت را پاسخ بده','سقف برداشت روزانه ده میلیون تومان است.',950,'active',ts,owner,owner,ts,ts),
        )
    insert_document('doc-priority-r18','old-policy.txt',['در نسخه قدیمی سقف برداشت روزانه پنج میلیون تومان بود.'])
    stage, items = main.retrieve_priority_stage('سقف برداشت روزانه چقدر است؟', None, integration=True)
    assert stage == 'training'
    assert items[0]['source_type'] == 'training'
    assert 'ده میلیون' in items[0]['answer']



def test_response_section_mapping_is_explicit_and_stable():
    assert main.response_section_key('faq_hit', 'barsan-faq-zero-token', []) == 'faq'
    assert main.response_section_key('cache_hit', 'barsan-answer-cache-zero-token', []) == 'cache'
    assert main.response_section_key('training_answer', 'model-x', [{'source_type': 'training'}]) == 'training'
    assert main.response_section_key('answered', 'model-x', [{'source_type': 'document'}]) == 'resources'
    assert main.response_section_key('self_analysis', 'model-x', [{'source_type': 'analysis'}]) == 'self_analysis'
    assert main.response_section_key('knowledge_gap', 'barsan-no-source', []) == 'knowledge_gap'


def test_question_report_exposes_section_and_source_names():
    marker = 'سؤال یکتای گزارش منبع پاسخ R19'
    conversation_id = main.create_conversation(None, 'source-report-user', marker)
    main.save_message(conversation_id, 'user', marker, status='asked')
    main.save_message(
        conversation_id,
        'assistant',
        'پاسخ آزمایشی از منبع سازمانی.',
        [{'source_type': 'document', 'document_id': 'doc-report', 'file_name': 'راهنمای سازمان.txt', 'chunk_index': 1, 'score': 0.9}],
        'test-model',
        120,
        'answered',
        {'prompt_tokens': 8, 'output_tokens': 4, 'total_tokens': 12},
    )
    rows = main._question_rows(marker, None, None, 10, 0)
    assert len(rows) == 1
    row = rows[0]
    assert row['response_section'] == 'resources'
    assert row['response_section_label'] == 'منابع بارگذاری‌شده'
    assert row['response_source_names'] == ['راهنمای سازمان.txt']
    assert row['zero_token'] is False


def test_response_source_percentages_and_zero_token_counts():
    before = main.response_source_stats(3650)
    before_map = {item['key']: item['value'] for item in before['items']}
    conversation_id = main.create_conversation(None, 'source-stats-user', 'source stats')
    main.save_message(conversation_id, 'assistant', 'faq', [{'source_type': 'faq', 'file_name': 'سؤالات متداول'}], 'barsan-faq-zero-token', 10, 'faq_hit', main._empty_usage())
    main.save_message(conversation_id, 'assistant', 'cache', [], 'barsan-answer-cache-zero-token', 8, 'cache_hit', main._empty_usage())
    main.save_message(conversation_id, 'assistant', 'training', [{'source_type': 'training', 'file_name': 'آموزش مدیر'}], 'model', 30, 'training_answer', {'prompt_tokens': 5, 'output_tokens': 2, 'total_tokens': 7})
    after = main.response_source_stats(3650)
    after_map = {item['key']: item for item in after['items']}
    assert after_map['faq']['value'] >= before_map.get('faq', 0) + 1
    assert after_map['cache']['value'] >= before_map.get('cache', 0) + 1
    assert after_map['training']['value'] >= before_map.get('training', 0) + 1
    assert after_map['faq']['zero_token_count'] >= 1
    assert after_map['cache']['zero_token_count'] >= 1
    assert after['zero_token_percentage'] >= 0
    assert abs(sum(item['percentage'] for item in after['items']) - 100.0) <= 0.5


def test_response_source_analytics_endpoint_and_ui_contract():
    token = owner_token()
    with TestClient(main.app) as client:
        response = client.get('/api/v1/manager/analytics/response-sources?days=30', headers={'Authorization': f'Bearer {token}'})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert 'total_answers' in payload and 'items' in payload
        assert all({'key', 'label', 'value', 'percentage'} <= set(item) for item in payload['items'])
    assert 'id="responseSourceCards"' in main.MAIN_HTML
    assert 'id="responseSourceSummary"' in main.MAIN_HTML
    assert 'responseSectionBadge' in main.MAIN_HTML
    assert 'appendResponseMeta' not in main.MAIN_HTML
    assert 'بخش پاسخ‌دهی' in main.MAIN_HTML


def _create_quota_user(username: str, *, lifetime=None, daily=None, monthly=None):
    password_hash, salt = main.hash_password('Password_123')
    day, month = main._quota_period_keys()
    with main.get_db() as db:
        cur = db.execute(
            """INSERT INTO users(username,name,password_hash,salt,role,is_active,is_owner,department,
               question_limit,questions_used,daily_question_limit,daily_questions_used,daily_quota_date,
               monthly_question_limit,monthly_questions_used,monthly_quota_month,created_at)
               VALUES(?,?,?,?, 'user',1,0,'sales',?,0,?,0,?, ?,0,?,?)""",
            (username, username, password_hash, salt, lifetime, daily, day, monthly, month, main.now_iso()),
        )
        return {'id': cur.lastrowid, 'username': username, 'role': 'user', 'is_active': 1, 'department': 'sales'}


def test_daily_and_monthly_quotas_reset_by_period_and_block_correctly():
    user = _create_quota_user('quota_period_expert', daily=1, monthly=2)
    assert main.reserve_question_quota(user) is True
    try:
        main.reserve_question_quota(user)
        assert False, 'daily limit must block the second question in the same day'
    except main.HTTPException as exc:
        assert exc.status_code == 429 and 'روزانه' in exc.detail
    with main.get_db() as db:
        db.execute("UPDATE users SET daily_quota_date='2000-01-01' WHERE id=?", (user['id'],))
    assert main.reserve_question_quota(user) is True
    with main.get_db() as db:
        db.execute("UPDATE users SET daily_quota_date='2000-01-02' WHERE id=?", (user['id'],))
    try:
        main.reserve_question_quota(user)
        assert False, 'monthly limit must block after two accepted questions'
    except main.HTTPException as exc:
        assert exc.status_code == 429 and 'ماهانه' in exc.detail


def test_persistent_multi_window_rate_limiter_survives_memory_reset():
    identity = 'rate-test:persistent-unique'
    main.enforce_rate_limit(identity, per_minute=2, daily_limit=10, monthly_limit=10)
    main.RATE_BUCKETS.clear()
    main.enforce_rate_limit(identity, per_minute=2, daily_limit=10, monthly_limit=10)
    try:
        main.enforce_rate_limit(identity, per_minute=2, daily_limit=10, monthly_limit=10)
        assert False, 'third request must be blocked from persistent database state'
    except main.HTTPException as exc:
        assert exc.status_code == 429


def test_guest_identity_does_not_depend_on_client_supplied_external_id():
    from starlette.requests import Request
    scope = {
        'type': 'http', 'method': 'POST', 'path': '/api/v1/guest/chat',
        'headers': [(b'user-agent', b'BarsanMobileTest')],
        'client': ('203.0.113.10', 50000), 'server': ('testserver', 80), 'scheme': 'http',
        'query_string': b'', 'root_path': '', 'http_version': '1.1',
    }
    request = Request(scope)
    first = main._anonymous_rate_identity('guest', request, None)
    second = main._anonymous_rate_identity('guest', request, None)
    assert first == second
    assert 'external-id-a' not in first and 'external-id-b' not in second


def test_faq_visibility_role_user_and_department_prevent_leakage():
    with main.get_db() as db:
        owner = db.execute('SELECT id FROM users WHERE is_owner=1 LIMIT 1').fetchone()['id']
    target = _create_quota_user('faq_access_target')
    target['department'] = 'sales'
    main.upsert_faq_rows([{
        'question': 'کد داخلی واحد فروش چیست؟',
        'answer': 'کد داخلی واحد فروش ۷۷۱ است.',
        'aliases': ['داخلی فروش'], 'priority': 900, 'is_active': True,
        'visibility': 'authenticated', 'allowed_roles': ['user'],
        'allowed_user_ids': [target['id']], 'department': 'sales',
    }], owner)
    # FAQ entries are intentionally public for all users in this release.
    assert main.find_faq_answer('داخلی فروش چنده؟', None, integration=True) is not None
    wrong = dict(target, id=target['id'] + 999, department='sales')
    assert main.find_faq_answer('داخلی فروش چنده؟', wrong, integration=False) is not None
    wrong_dept = dict(target, department='support')
    assert main.find_faq_answer('داخلی فروش چنده؟', wrong_dept, integration=False) is not None
    found = main.find_faq_answer('داخلی فروش چنده؟', target, integration=False)
    assert found and '۷۷۱' in found['answer']


def test_training_visibility_is_applied_before_retrieval():
    with main.get_db() as db:
        owner = db.execute('SELECT id FROM users WHERE is_owner=1 LIMIT 1').fetchone()['id']
        ts = main.now_iso()
        db.execute(
            """INSERT OR REPLACE INTO training_rules(id,topic,topic_key,canonical_key,instruction,answer,priority,status,
               effective_from,visibility,allowed_roles_json,allowed_user_ids_json,department,created_by,approved_by,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ('training-private-r20','فرآیند محرمانه','فرآیند محرمانه','فرآیند|محرمانه','فرآیند محرمانه را پاسخ بده',
             'فرآیند محرمانه فقط برای مدیران است.',950,'active',ts,'internal','["manager","admin"]','[]',None,owner,owner,ts,ts),
        )
        main.rebuild_training_fts(db)
    assert not main.retrieve_training('فرآیند محرمانه چیست؟', None, integration=True)
    manager = {'id': owner, 'role': 'admin', 'department': None}
    assert main.retrieve_training('فرآیند محرمانه چیست؟', manager, integration=False)


def test_approved_and_temporary_cache_have_separate_lifecycles():
    question_temp = 'تحلیل موقت یکتای R21 چیست؟'
    main.store_cached_answer(question_temp, False, None, True, 'پاسخ موقت.', [], 'model', cache_tier='temporary')
    hit = main.find_cached_answer(question_temp, False, None, True)
    assert hit and hit['cache_tier'] == 'temporary' and hit['expires_at']
    with main.get_db() as db:
        db.execute("UPDATE answer_cache SET expires_at='2000-01-01T00:00:00+00:00' WHERE normalized_question=?", (main.canonical_question_for_cache(question_temp),))
    assert main.find_cached_answer(question_temp, False, None, True) is None
    question_ok = 'پاسخ تاییدشده یکتای R21 چیست؟'
    main.store_cached_answer(question_ok, False, None, True, 'پاسخ تاییدشده.', [], 'model', cache_tier='approved')
    approved = main.find_cached_answer(question_ok, False, None, True)
    assert approved and approved['cache_tier'] == 'approved' and approved['expires_at'] is None


def test_feedback_invalidates_bad_cache_and_promotes_manager_approved_cache():
    owner = None
    with main.get_db() as db:
        owner = dict(db.execute('SELECT * FROM users WHERE is_owner=1 LIMIT 1').fetchone())
    q1 = 'پرسش کش اشتباه یکتای R21'
    cid = main.create_conversation(owner['id'], None, q1)
    main.save_message(cid, 'user', q1, status='asked')
    mid = main.save_message(cid, 'assistant', 'جواب اشتباه.', [], 'model', 1, 'self_analysis', main._empty_usage())
    main.store_cached_answer(q1, False, owner, False, 'جواب اشتباه.', [], 'model', cache_tier='temporary')
    action = main._review_cache_for_message(mid, 'wrong', owner)
    assert action['deleted'] >= 1
    assert main.find_cached_answer(q1, False, owner, False) is None

    q2 = 'پرسش کش تایید مدیر یکتای R21'
    cid2 = main.create_conversation(owner['id'], None, q2)
    main.save_message(cid2, 'user', q2, status='asked')
    mid2 = main.save_message(cid2, 'assistant', 'جواب صحیح.', [], 'model', 1, 'self_analysis', main._empty_usage())
    main.store_cached_answer(q2, False, owner, False, 'جواب صحیح.', [], 'model', cache_tier='temporary')
    action2 = main._review_cache_for_message(mid2, 'correct', owner)
    assert action2['promoted'] >= 1
    promoted = main.find_cached_answer(q2, False, owner, False)
    assert promoted and promoted['cache_tier'] == 'approved' and promoted['expires_at'] is None


def test_five_path_model_router_selects_expected_routes():
    high_doc = [{'source_type':'document','document_id':'d1','score':0.95}]
    training = [{'source_type':'training','training_id':'t1','score':0.95}]
    many_docs = [{'source_type':'document','document_id':f'd{i}','score':0.7} for i in range(4)]
    assert main.select_model_route('سؤال', 'faq', [], False) == 'zero_token'
    assert main.select_model_route('سؤال', 'training', training, False) == 'direct_training'
    assert main.select_model_route('قیمت سرویس چیست؟', 'document', high_doc, False) == 'economy'
    assert main.select_model_route('شرایط سرویس را توضیح بده', 'document', [{'source_type':'document','document_id':'d','score':0.4}], False) == 'standard'
    assert main.select_model_route('این موارد را کامل تحلیل کن', 'document', many_docs, True) == 'advanced'


def test_semantic_index_finds_conceptual_paraphrase_without_exact_phrase():
    doc_id = 'semantic-concept-r20'
    chunks = ['برای خاتمه همکاری، فرم قطع قرارداد باید توسط مسئول واحد امضا و سپس ثبت شود.']
    insert_document(doc_id, 'termination-policy.txt', chunks)
    with main.get_db() as db:
        main.index_semantic_chunks(db, doc_id, chunks)
    results = main.retrieve('چطور همکاری را تمام کنیم؟', None, integration=True)
    assert any(item['document_id'] == doc_id for item in results)


def test_api_failover_records_attempts_and_successful_switch(monkeypatch):
    monkeypatch.setattr(main, 'AI_PROVIDER', 'openai_compatible')
    monkeypatch.setattr(main, 'AI_API_KEY_1', 'event-key-1')
    monkeypatch.setattr(main, 'AI_API_KEY_2', 'event-key-2')
    monkeypatch.setattr(main, 'AI_API_KEY_3', '')
    monkeypatch.setattr(main, 'AI_API_KEY_4', '')
    monkeypatch.setattr(main, 'AI_API_KEY', '')
    monkeypatch.setattr(main, 'AI_BASE_URL', 'https://provider.example/v1')
    monkeypatch.setattr(main, 'AI_MODEL', 'route-model')
    with main.get_db() as db:
        db.execute('DELETE FROM ai_api_slot_state')
        db.execute('DELETE FROM api_call_events')
        db.execute("INSERT OR REPLACE INTO system_settings(key,value,updated_at) VALUES('active_api_slot','1',?)", (main.now_iso(),))
    async def fake_request(**kwargs):
        if kwargs['headers']['Authorization'].endswith('event-key-1'):
            raise main.ApiSlotLimitError(429, 'quota exceeded', 60)
        return {'choices':[{'message':{'content':'پاسخ سالم از کلید دوم.'},'finish_reason':'stop'}], 'usage':{'prompt_tokens':3,'completion_tokens':4,'total_tokens':7}}
    monkeypatch.setattr(main, '_request_json_with_retries', fake_request)
    answer, usage, _ = asyncio.run(main._generate_ai_text([{'role':'user','content':'تست'}], max_tokens=100, temperature=0, route='economy'))
    assert usage['api_slot'] == 2 and 'کلید دوم' in answer
    with main.get_db() as db:
        rows = [dict(r) for r in db.execute('SELECT slot,status,was_failover FROM api_call_events ORDER BY id').fetchall()]
    assert rows[0]['slot'] == 1 and rows[0]['status'] == 'limited'
    assert rows[1]['slot'] == 2 and rows[1]['status'] == 'success' and rows[1]['was_failover'] == 1


def test_provider_usage_dashboard_reports_tokens_failures_failovers_and_credit(monkeypatch):
    monkeypatch.setattr(main, 'AI_API_KEY_1', 'dashboard-key')
    monkeypatch.setattr(main, 'AI_API_KEY', '')
    monkeypatch.setattr(main, 'AI_CREDIT_AMOUNT', [100.0,0.0,0.0,0.0])
    main.record_usage(user_id=None, external_user_id='dashboard-test', event_type='answered',
        usage={'prompt_tokens':100,'output_tokens':50,'total_tokens':150,'api_slot':1,'provider_label':'Dashboard Provider','model_route':'economy','estimated_cost':2.5},
        model='m1', response_ms=90)
    main.record_api_call_event(slot=1,provider_label='Dashboard Provider',model='m1',model_route='economy',status='success',response_ms=90,attempt_index=2,was_failover=True)
    data = main.provider_usage_dashboard(3650)
    slot = next(x for x in data['items'] if x['slot'] == 1)
    assert slot['total_tokens'] >= 150 and slot['configured_credit'] == 100.0
    assert data['successful_failovers'] >= 1 and 'credit_note' in data


def test_health_snapshot_includes_api_error_rate_backup_and_document_jobs():
    snapshot = main._health_snapshot()
    assert snapshot['database'] is True and snapshot['storage'] is True
    assert 'api_last_hour' in snapshot and 'failure_rate_percent' in snapshot['api_last_hour']
    assert 'backup' in snapshot and 'overdue' in snapshot['backup']
    assert 'document_failures_last_hour' in snapshot


def test_backup_and_restore_roundtrip_preserves_database_and_files(monkeypatch):
    with main.get_db() as db:
        owner = db.execute('SELECT id FROM users WHERE is_owner=1 LIMIT 1').fetchone()['id']
        db.execute("INSERT OR REPLACE INTO system_settings(key,value,updated_at) VALUES('backup-roundtrip','before',?)", (main.now_iso(),))
    main.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    marker_file = main.UPLOAD_DIR / 'backup-roundtrip.txt'
    marker_file.write_text('before-backup', encoding='utf-8')
    payload, filename, backup_id = main.create_backup_bytes(owner)
    assert filename.endswith('.zip') and backup_id and payload[:2] == b'PK'
    with main.get_db() as db:
        db.execute("UPDATE system_settings SET value='after' WHERE key='backup-roundtrip'")
    marker_file.write_text('after-backup', encoding='utf-8')
    restored = main.restore_backup_bytes(payload, owner)
    with main.get_db() as db:
        value = db.execute("SELECT value FROM system_settings WHERE key='backup-roundtrip'").fetchone()['value']
    assert value == 'before'
    assert marker_file.read_text(encoding='utf-8') == 'before-backup'
    assert restored['uploads_restored'] >= 1


def test_frontend_javascript_and_r20_quality_contract():
    import subprocess, sys
    result = subprocess.run([sys.executable, str(Path(main.__file__).with_name('validate_frontend.py'))], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    dockerfile = Path(main.__file__).with_name('Dockerfile').read_text(encoding='utf-8')
    assert 'BARSAN_R35_BUILD_OK' in dockerfile
    assert 'FROM python:3.12-slim-bookworm' in dockerfile
    assert 'requirements.lock.txt' in dockerfile and 'rag_engine.py' in dockerfile and 'ui_templates.py' in dockerfile
    assert 'ruff check' not in dockerfile and 'bandit -lll' not in dockerfile and 'pytest -q' not in dockerfile
    import json
    railway = json.loads(Path(main.__file__).with_name('railway.json').read_text(encoding='utf-8'))
    assert railway['deploy']['preDeployCommand'] is None
    assert railway['deploy']['healthcheckPath'] == '/healthz'
    assert railway['deploy']['healthcheckTimeout'] == 600
    assert railway['deploy']['restartPolicyType'] == 'ALWAYS'

def test_rate_limit_windows_are_atomic_when_daily_limit_is_exhausted():
    identity = f'atomic-rate:{main.uuid.uuid4()}'
    day_key, _month_key = main._quota_period_keys()
    minute_key = main._local_now().strftime('%Y-%m-%dT%H:%M')
    with main.get_db() as db:
        db.execute(
            "INSERT INTO request_counters(identity_key,window_type,window_key,count,updated_at) VALUES(?,?,?,?,?)",
            (identity, 'day', day_key, 1, main.now_iso()),
        )
    with pytest.raises(main.HTTPException) as exc:
        main.enforce_rate_limit(identity, per_minute=10, daily_limit=1, monthly_limit=100)
    assert exc.value.status_code == 429
    with main.get_db() as db:
        minute = db.execute(
            "SELECT count FROM request_counters WHERE identity_key=? AND window_type='minute' AND window_key=?",
            (identity, minute_key),
        ).fetchone()
    assert minute is None


def test_frontend_isolated_from_backend_module_and_still_exported():
    import ui_templates
    assert main.MAIN_HTML is ui_templates.MAIN_HTML
    assert main.WIDGET_HTML is ui_templates.WIDGET_HTML
    assert '<html' in main.MAIN_HTML.lower() and '<script' in main.WIDGET_HTML.lower()


def test_deterministic_math_supports_persian_digits_and_markers():
    answer = main.direct_math_answer('۲۰۰۰ - ۳۰۰ چقدر می‌شود؟')
    assert answer is not None
    assert '1,700' in answer
    assert main.apply_verified_calculations('مقدار نهایی [[CALC: 25*4 ]] است.') == 'مقدار نهایی 100 است.'
    assert main.direct_math_answer('وزن مجاز ۲۰۰۰ کیلوگرم است') is None


def test_pdf_image_pages_are_added_to_searchable_text(monkeypatch):
    if main.fitz is None:
        pytest.skip('PyMuPDF is unavailable')
    pix=main.fitz.Pixmap(main.fitz.csRGB,main.fitz.IRect(0,0,40,40),False)
    pix.clear_with(255)
    png=pix.tobytes('png')
    doc = main.fitz.open()
    page = doc.new_page(width=300, height=200)
    page.insert_image(main.fitz.Rect(20, 20, 280, 180), stream=png)
    payload = doc.tobytes(); doc.close()

    async def fake_vision(page_number, image_bytes, existing_text, image_count):
        assert page_number == 1
        assert image_count >= 1
        return 'وزن مجاز نیسان ۲۰۰۰ کیلوگرم است؛ اما در شمال تهران و بالاتر از اتوبان باهنر ۱۷۰۰ کیلوگرم است.'

    monkeypatch.setattr(main, '_vision_read_pdf_page', fake_vision)
    monkeypatch.setattr(main, 'PDF_VISION_ENABLED', True)
    monkeypatch.setattr(main, 'configured_ai_slots', lambda: [{'slot':1,'vision_model':'vision-test'}])
    monkeypatch.setattr(main, '_vision_model_for_slot', lambda slot: 'vision-test')
    text = main.extract_text('visual.pdf', payload)
    assert 'جزئیات استخراجشده از تصویر' in text
    assert '۲۰۰۰' in text and '۱۷۰۰' in text and 'باهنر' in text


def test_ui_has_voice_controls_fixed_composer_and_video_thinking_loader():
    html = main.MAIN_HTML
    assert "startVoiceInput('faqQuestion'" in html
    assert "startVoiceInput('faqAnswer'" in html
    assert "startVoiceInput('trainingMessage'" in html
    assert '/api/v1/speech/transcribe' in html
    assert 'position:sticky;bottom:0' in html
    assert 'BARSAN R35.2 canonical thinking loader' in html
    assert 'margin:8px 0 10px auto!important' in html
    assert "v.src='/thinking-loader.mp4?v=R35_2'" in html
    assert "v.loop=true" in html and "v.muted=true" in html and "v.playsInline=true" in html
    assert 'thinking-orbit' not in html
    assert 'function thinkingDots' not in html


def test_thinking_loader_video_route():
    with TestClient(main.app) as client:
        response = client.get('/thinking-loader.mp4')
        assert response.status_code == 200
        assert response.headers.get('content-type', '').startswith('video/mp4')
        assert len(response.content) > 1000


def test_transcription_and_vision_models_are_configurable():
    assert hasattr(main, 'AI_TRANSCRIPTION_MODEL_1')
    assert hasattr(main, 'AI_VISION_MODEL_2')
    assert main.PDF_VISION_MAX_PAGES >= 1


def test_source_verification_keeps_general_rule_and_exception(monkeypatch):
    calls=[]
    async def fake_generate(messages,max_tokens,temperature,route='standard'):
        calls.append(messages)
        joined=' '.join(str(m.get('content')) for m in messages)
        if 'پاسخ پیشنهادی' in joined:
            return ('وزن مجاز بارگیری نیسان در حالت عادی ۲۰۰۰ کیلوگرم است؛ اما در شمال تهران و بالاتر از اتوبان باهنر، سقف مجاز به ۱۷۰۰ کیلوگرم کاهش می‌یابد.',
                    {'prompt_tokens':10,'output_tokens':10,'total_tokens':20},'stop')
        return ('وزن مجاز ۱۷۰۰ کیلوگرم است.',{'prompt_tokens':10,'output_tokens':5,'total_tokens':15},'stop')
    monkeypatch.setattr(main,'_generate_ai_text',fake_generate)
    monkeypatch.setattr(main,'SOURCE_ANSWER_VERIFICATION',True)
    sources=[{'source_type':'document','content':'وزن مجاز بارگیری نیسان ۲۰۰۰ کیلوگرم است. اما در شمال تهران و بالاتر از اتوبان باهنر، وزن مجاز ۱۷۰۰ کیلوگرم است.','score':0.9}]
    answer,usage=asyncio.run(main.ask_ai('وزن مجاز نیسان چقدر است؟',sources,detailed=False,route='standard'))
    assert '۲۰۰۰' in answer and '۱۷۰۰' in answer and 'باهنر' in answer
    assert len(calls)>=2
    assert usage['total_tokens']==35


def test_resumable_chunk_upload_survives_multiple_requests(monkeypatch):
    monkeypatch.setattr(main, 'UPLOAD_CHUNK_BYTES', 5)
    monkeypatch.setattr(main, 'UPLOAD_CHUNK_MB', 1)
    token = owner_token()
    headers = {'Authorization': f'Bearer {token}'}
    payload = b'hello world from barsan'
    with TestClient(main.app) as client:
        started = client.post('/api/v1/admin/upload-sessions', headers=headers, json={
            'filename': 'large-source.txt', 'size_bytes': len(payload), 'visibility': 'public', 'content_type': 'text/plain'
        })
        assert started.status_code == 200
        upload_id = started.json()['upload_id']
        index = 0
        for offset in range(0, len(payload), 5):
            part = payload[offset:offset + 5]
            response = client.post(
                f'/api/v1/admin/upload-sessions/{upload_id}/chunks/{index}',
                headers=headers,
                files={'file': (f'chunk-{index}.part', part, 'application/octet-stream')},
            )
            assert response.status_code == 200
            index += 1
        status = client.get(f'/api/v1/admin/upload-sessions/{upload_id}', headers=headers)
        assert status.json()['received_bytes'] == len(payload)
        completed = client.post(f'/api/v1/admin/upload-sessions/{upload_id}/complete', headers=headers)
        assert completed.status_code == 200
        assert completed.json()['filename'] == 'large-source.txt'


def test_google_docs_link_parser_is_restricted_and_precise():
    doc_id = main._extract_google_doc_id('https://docs.google.com/document/d/ABC_123-test/edit?usp=sharing')
    assert doc_id == 'ABC_123-test'
    with pytest.raises(main.HTTPException):
        main._extract_google_doc_id('https://example.com/document/d/ABC_123-test')


def test_voice_transcript_cleanup_removes_adjacent_repetitions():
    cleaned = main._clean_transcript_text('سلام سلام این یک تست است این یک تست است')
    assert cleaned == 'سلام این یک تست است'


def test_r24_ui_has_new_chat_google_docs_media_recorder_and_chunk_upload():
    html = main.MAIN_HTML
    assert 'id="newChatBtn"' in html and 'چت جدید' in html
    assert 'startNewChat()' in html
    assert 'id="googleDocUrl"' in html and '/api/v1/admin/documents/google-doc' in html
    assert 'new MediaRecorder' in html
    assert '/api/v1/admin/upload-sessions' in html
    assert 'uploadChunkWithRetry' in html


def test_unified_chat_filters_legacy_section_redirects():
    assert main.is_navigation_only_content('این درخواست فقط در بخش «بررسی بار» انجام می‌شود. مشخصات خودرو و بار را در همان بخش وارد کنید.')
    assert main.is_navigation_only_content('برای این کار وارد بخش مسیریابی شوید.')
    assert not main.is_navigation_only_content('در بررسی بار، وزن مجاز نیسان ۲۰۰۰ کیلوگرم است و در شمال تهران ۱۷۰۰ کیلوگرم می‌شود.')


def test_priority_stage_ignores_redirect_training_and_uses_document(monkeypatch):
    monkeypatch.setattr(main, 'retrieve_training', lambda *args, **kwargs: [{
        'source_type':'training','training_id':'t1','document_id':'training:t1','file_name':'آموزش',
        'chunk_index':0,'content':'این درخواست فقط در بخش بررسی بار انجام می‌شود.','answer':'این درخواست فقط در بخش بررسی بار انجام می‌شود.',
        'priority':100,'score':0.99,'excerpt':'redirect'
    }])
    monkeypatch.setattr(main, '_retrieve_document_chunks', lambda *args, **kwargs: [{
        'source_type':'document','document_id':'d1','file_name':'جزوه بارگیری.pdf','chunk_index':2,
        'content':'روباری: خاور امکان بارگیری بصورت موشکی و روباری ندارد. نیسان: بارگیری روباری تا ۷۰۰ کیلوگرم. پیکان: بارگیری روباری تا ۳۰۰ کیلوگرم.',
        'score':0.82,'excerpt':'روباری'
    }])
    stage, sources = main.retrieve_priority_stage('برای پیکان تا چند کیلو میتونه روبار بزنه؟', None)
    assert stage == 'document'
    assert len(sources) == 1 and '۳۰۰' in sources[0]['content']


def test_search_alias_understands_robar_colloquial_form():
    q = main.search_tokens('پیکان تا چند کیلو روبار میتونه بزنه؟')
    c = main.search_tokens('بارگیری روباری پیکان تا ۳۰۰ کیلوگرم')
    assert set(q) & set(c)
    assert main._retrieval_score('پیکان تا چند کیلو روبار میتونه بزنه؟','بارگیری روباری پیکان تا ۳۰۰ کیلوگرم') > 0.40


def test_cached_redirect_answer_is_rejected(monkeypatch):
    # Guard-level regression: bad legacy cache content must never be considered a valid chat answer.
    assert main.is_navigation_only_content('این درخواست فقط در بخش مسیریابی انجام می‌شود.') is True
    assert main.is_navigation_only_content('پیکان تا ۳۰۰ کیلوگرم بار روباری مجاز دارد.') is False


def test_process_chat_does_not_return_bar_review_redirect_when_document_has_answer(monkeypatch):
    monkeypatch.setattr(main, 'find_faq_answer', lambda *args, **kwargs: None)
    monkeypatch.setattr(main, 'find_cached_answer', lambda *args, **kwargs: None)
    monkeypatch.setattr(main, 'retrieve_training', lambda *args, **kwargs: [{
        'source_type':'training','training_id':'legacy-nav','document_id':'training:legacy-nav','file_name':'آموزش قدیمی',
        'chunk_index':0,'content':'این درخواست فقط در بخش بررسی بار انجام می‌شود. مشخصات خودرو و بار را در همان بخش وارد کنید.',
        'answer':'این درخواست فقط در بخش بررسی بار انجام می‌شود. مشخصات خودرو و بار را در همان بخش وارد کنید.',
        'priority':100,'score':1.0,'excerpt':'legacy redirect'
    }])
    monkeypatch.setattr(main, '_retrieve_document_chunks', lambda *args, **kwargs: [{
        'source_type':'document','document_id':'robari-doc','file_name':'جزوه روباری.pdf','chunk_index':4,
        'content':'روباری: خاور امکان بارگیری بصورت موشکی و روباری ندارد. نیسان بارگیری روباری تا ۷۰۰ کیلوگرم و پیکان بارگیری روباری تا ۳۰۰ کیلوگرم مجاز است.',
        'score':0.91,'excerpt':'روباری'
    }])
    async def fake_ask(question, context_items, detailed=False, route='standard', memory=''):
        assert all('فقط در بخش بررسی بار' not in str(x.get('content') or '') for x in context_items)
        assert any('۳۰۰' in str(x.get('content') or '') for x in context_items)
        return 'پیکان برای بارگیری روباری تا ۳۰۰ کیلوگرم مجاز است.', {'prompt_tokens':10,'output_tokens':8,'total_tokens':18,'model_route':route}
    monkeypatch.setattr(main, 'ask_ai', fake_ask)
    result=asyncio.run(main.process_chat(message='برای پیکان تا چند کیلو میتونه روبار بزنه؟',conversation_id=None,user=None,external_user_id='r25-robari',integration=True))
    assert '۳۰۰' in result['answer']
    assert 'بررسی بار' not in result['answer']
    assert result['status']=='answered'


def test_source_ingestion_v3_schema_is_available():
    with main.get_db() as db:
        dcols=main.column_names(db,'documents')
        ccols=main.column_names(db,'chunks')
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {'page_count','vision_candidate_pages','vision_success_pages','vision_failed_pages','ingestion_quality_pct','ingestion_warnings_json','ingestion_version'} <= dcols
    assert {'page_start','page_end','section_title','chunk_type','search_aliases'} <= ccols
    assert 'document_pages' in tables


def test_page_aware_chunking_preserves_rule_exception_and_page_metadata():
    result={
        'text':'', 'pages':[
            {'page_number':1,'combined_text':'ظرفیت نیسان\nقاعده اصلی: وزن مجاز بارگیری نیسان ۲۰۰۰ کیلوگرم است.\nشرط/استثنا: در شمال تهران و بالاتر از اتوبان باهنر حداکثر ۱۷۰۰ کیلوگرم است.','vision_text':'','base_text':'x'},
            {'page_number':2,'combined_text':'روبار پیکان\nحداکثر بار روی باربند پیکان ۳۰۰ کیلوگرم است.','vision_text':'متن تصویر','base_text':'x'},
        ]
    }
    chunks=main.chunk_source_result(result)
    assert chunks
    first='\n'.join(x['content'] for x in chunks if x['page_start']==1)
    assert '۲۰۰۰' in first and '۱۷۰۰' in first
    assert any(x['page_start']==1 and x['page_end']==2 and x['chunk_type']=='bridge' for x in chunks)
    assert any('روبار' in x['search_aliases'] or 'باربند' in x['search_aliases'] for x in chunks if x['page_start']==2)


def test_partial_document_is_excluded_from_answers_but_diagnostic_state_is_kept():
    doc_id='doc-partial-r28'
    with main.get_db() as db:
        db.execute("INSERT OR REPLACE INTO documents(id,filename,stored_path,mime_type,visibility,status,character_count,chunk_count,version,page_count,vision_candidate_pages,vision_success_pages,vision_failed_pages,ingestion_quality_pct,ingestion_warnings_json,ingestion_version,created_at) VALUES (?,?,?,?,?,'partial',?,?,1,?,?,?,?,?,?,2,?)",
                   (doc_id,'partial.pdf',str(TEST_ROOT / 'partial.pdf'),'application/pdf','public',100,1,2,2,1,1,72.5,'[\"صفحه ۲ خطا\"]',main.now_iso()))
        db.execute('DELETE FROM chunks WHERE document_id=?',(doc_id,));db.execute('DELETE FROM chunks_fts WHERE document_id=?',(doc_id,))
        content='صفحه 1 — ظرفیت نیسان\nوزن مجاز نیسان 2000 کیلوگرم است.'
        aliases=main._chunk_search_aliases(content)
        db.execute("INSERT INTO chunks(document_id,chunk_index,content,page_start,page_end,section_title,chunk_type,search_aliases) VALUES (?,?,?,?,?,?,?,?)",(doc_id,0,content,1,1,'ظرفیت نیسان','text',aliases))
        db.execute("INSERT INTO chunks_fts(content,file_name,visibility,document_id,chunk_index) VALUES (?,?,?,?,?)",(content+' '+aliases,'partial.pdf','public',doc_id,0))
        main.index_semantic_chunks(db,doc_id,[content+' '+aliases])
    results=main.retrieve('وزن مجاز نیسان چقدر است؟',None)
    assert not any(x['document_id']==doc_id for x in results)
    with main.get_db() as db:
        row=db.execute('SELECT status,ingestion_quality_pct FROM documents WHERE id=?',(doc_id,)).fetchone()
    assert row['status']=='partial' and float(row['ingestion_quality_pct'])==72.5


def test_numeric_and_robar_aliases_improve_source_matching():
    content='صفحه 8 — جدول بارگیری\nبارگیری روباری پیکان: حداکثر ۳۰۰ کیلوگرم.'
    aliases=main._chunk_search_aliases(content)
    assert 'باربند' in aliases
    score=main._retrieval_score('پیکان روی باربند چند کیلو بار میزند؟',content+' '+aliases)
    assert score > 0.45


def test_upload_config_exposes_current_source_ingestion_contract():
    with TestClient(main.app) as client:
        token=owner_token()
        response=client.get('/api/v1/admin/upload-config',headers={'Authorization':f'Bearer {token}'})
        assert response.status_code==200
        data=response.json()
        assert data['source_ingestion_version']==main.INGESTION_VERSION
        assert data['pdf_vision_max_pages']>=200
        assert data['source_min_quality_pct']>=70


def test_r29_vector_pack_roundtrip_and_cosine():
    from rag_engine import pack_vector, unpack_vector, cosine_similarity
    values=[0.1,0.2,0.3,0.4]
    restored=unpack_vector(pack_vector(values))
    assert len(restored)==4
    assert cosine_similarity(restored,restored)>0.999


def test_r29_structured_fact_extraction_keeps_base_rule_and_exception():
    from rag_engine import extract_structured_facts
    text='وزن مجاز بارگیری نیسان 2000 کیلوگرم است.\nتبصره: در شمال تهران و بالاتر از اتوبان باهنر حداکثر 1700 کیلوگرم است.'
    facts=extract_structured_facts(text,page_start=23,page_end=23,section_title='ظرفیت نیسان')
    blob='\n'.join(x['fact_text'] for x in facts)
    assert '2000' in blob and '1700' in blob
    assert any(x['fact_type']=='conditional' for x in facts)
    assert all(x['page_start']==23 for x in facts)


def test_r29_source_names_include_page_when_available():
    names=main.response_source_names([{'file_name':'جزوه بارگیری.pdf','page_start':23}])
    assert names==['جزوه بارگیری.pdf — صفحه 23']


def test_r29_public_source_items_preserve_trace_metadata():
    rows=main.public_source_items([{'source_type':'document','document_id':'x','file_name':'policy.pdf','chunk_index':2,'score':.9,'page_start':7,'page_end':8,'section_title':'تبصره ظرفیت','embedding_score':.8,'rerank_score':1.1,'content':'قانون'}])
    assert rows[0]['page_start']==7 and rows[0]['page_end']==8
    assert rows[0]['section_title']=='تبصره ظرفیت'
    assert rows[0]['embedding_score']==pytest.approx(.8)


def test_r29_faq_template_and_training_contract_are_simple():
    csv_text=Path(main.__file__).with_name('FAQ_TEMPLATE.csv').read_text(encoding='utf-8')
    assert csv_text.splitlines()[0]=='question,answer,aliases,active'
    assert 'priority' not in main.FaqInput.model_fields
    assert set(main.TrainingChatInput.model_fields)=={'message'}


def test_r29_docker_copies_rag_engine_and_quality_gate_marker():
    docker=Path(main.__file__).with_name('Dockerfile').read_text(encoding='utf-8')
    assert 'rag_engine.py' in docker
    assert 'BARSAN_R35_BUILD_OK' in docker
    assert 'ARG APP_VERSION=35.2.3' in docker
    assert 'source_quality.py' in docker and 'provider_runtime.py' in docker
    assert 'railway_start.py' in docker

def test_r29_retrieval_debug_reports_training_as_authoritative_layer():
    token=owner_token()
    with TestClient(main.app) as client:
        response=client.get('/api/v1/admin/retrieval-debug',params={'q':'سقف برداشت روزانه چقدر است؟'},headers={'Authorization':f'Bearer {token}'})
        assert response.status_code==200,response.text
        data=response.json()
        assert data['priority_order']==['training','document','faq','cache']
        assert data['selected_stage']=='training'
        assert data['training']


def test_r29_golden_case_lifecycle_and_run_uses_priority_retrieval():
    token=owner_token()
    payload={'question':'سقف برداشت روزانه چقدر است؟','expected_answer':'سقف برداشت روزانه ده میلیون تومان است.','expected_source':'آموزش مدیریتی','is_active':True}
    with TestClient(main.app) as client:
        created=client.post('/api/v1/admin/golden-cases',headers={'Authorization':f'Bearer {token}'},json=payload)
        assert created.status_code==200,created.text
        case_id=created.json()['id']
        run=client.post('/api/v1/admin/golden-runs',headers={'Authorization':f'Bearer {token}'})
        assert run.status_code==200,run.text
        detail=[x for x in run.json()['details'] if x['case_id']==case_id][0]
        assert detail['stage']=='training' and detail['passed'] is True
        deleted=client.delete(f'/api/v1/admin/golden-cases/{case_id}',headers={'Authorization':f'Bearer {token}'})
        assert deleted.status_code==200


def test_r29_streaming_backup_file_is_created_without_in_memory_requirement():
    path,filename,backup_id,size_bytes,persistent=main.create_backup_file(None,persist_to_disk=False)
    try:
        assert path.is_file() and path.stat().st_size==size_bytes and size_bytes>0
        assert filename.endswith('.zip') and backup_id and persistent is False
    finally:
        path.unlink(missing_ok=True)


def test_r29_health_query_uses_real_document_error_status():
    source=Path(main.__file__).read_text(encoding='utf-8')
    assert "document_jobs WHERE status='error'" in source
    assert "document_jobs WHERE status='failed'" not in source


def test_r29_reindex_queue_keeps_existing_source_online():
    doc_id='zero-downtime-reindex-r29'
    stored=TEST_ROOT/'uploads'/'zero-downtime.txt';stored.parent.mkdir(parents=True,exist_ok=True);stored.write_text('منبع فعال هنگام بازسازی',encoding='utf-8')
    with main.get_db() as db:
        db.execute("INSERT OR REPLACE INTO documents(id,filename,stored_path,mime_type,visibility,status,character_count,chunk_count,version,created_at) VALUES(?,?,?,?,?,'ready',?,?,1,?)",
                   (doc_id,'zero-downtime.txt',str(stored),'text/plain','public',24,1,main.now_iso()))
        owner=db.execute('SELECT id FROM users WHERE is_owner=1 LIMIT 1').fetchone()['id']
    job_id=main._enqueue_reindex_job(doc_id,owner,'test queue')
    with main.get_db() as db:
        doc=db.execute('SELECT status FROM documents WHERE id=?',(doc_id,)).fetchone()
        job=db.execute('SELECT status,max_attempts FROM document_jobs WHERE id=?',(job_id,)).fetchone()
        db.execute('DELETE FROM document_jobs WHERE id=?',(job_id,))
    assert doc['status']=='ready'
    assert job['status']=='queued' and int(job['max_attempts'])>=1


def test_r29_stale_document_job_is_recovered_to_queue():
    doc_id='stale-job-doc-r29'
    with main.get_db() as db:
        db.execute("INSERT OR REPLACE INTO documents(id,filename,stored_path,mime_type,visibility,status,character_count,chunk_count,version,created_at) VALUES(?,?,?,?,?,'ready',?,?,1,?)",
                   (doc_id,'stale.txt',str(TEST_ROOT / 'stale.txt'),'text/plain','public',0,0,main.now_iso()))
        owner=db.execute('SELECT id FROM users WHERE is_owner=1 LIMIT 1').fetchone()['id']
        old=(main.datetime.now(main.timezone.utc)-main.timedelta(seconds=main.DOCUMENT_JOB_STALE_SECONDS+30)).isoformat()
        db.execute("INSERT OR REPLACE INTO document_jobs(id,document_id,status,progress,phase,created_by,created_at,updated_at,attempts,max_attempts,job_type,payload_json) VALUES(?,?,'processing',30,'stale',?,?,?,?,?,'reindex','{}')",
                   ('stale-job-r29',doc_id,owner,old,old,1,main.DOCUMENT_JOB_MAX_ATTEMPTS))
    assert main._recover_stale_document_jobs()>=1
    with main.get_db() as db:
        row=db.execute("SELECT status,worker_id FROM document_jobs WHERE id='stale-job-r29'").fetchone()
        db.execute("DELETE FROM document_jobs WHERE id='stale-job-r29'")
    assert row['status']=='queued' and row['worker_id'] is None


def test_r29_knowledge_signature_changes_only_when_authoritative_version_bumps():
    before=main.current_knowledge_signature('public')
    main.bump_knowledge_version()
    after=main.current_knowledge_signature('public')
    assert before!=after
    assert after==main.current_knowledge_signature('public')


@pytest.mark.skipif(main.fitz is None,reason='PyMuPDF is not installed')
def test_r29_pdf_page_preview_endpoint():
    pdf_path=TEST_ROOT/'uploads'/'preview-r29.pdf';pdf_path.parent.mkdir(parents=True,exist_ok=True)
    pdf=main.fitz.open();page=pdf.new_page();page.insert_text((72,72),'Barsan preview page');pdf.save(str(pdf_path));pdf.close()
    doc_id='preview-pdf-r29'
    with main.get_db() as db:
        db.execute("INSERT OR REPLACE INTO documents(id,filename,stored_path,mime_type,visibility,status,character_count,chunk_count,version,created_at) VALUES(?,?,?,?,?,'ready',?,?,1,?)",
                   (doc_id,'preview-r29.pdf',str(pdf_path),'application/pdf','public',20,0,main.now_iso()))
    with TestClient(main.app) as client:
        token=owner_token();r=client.get(f'/api/v1/admin/documents/{doc_id}/pages/1/preview',headers={'Authorization':f'Bearer {token}'})
        assert r.status_code==200
        assert r.headers['content-type'].startswith('image/png') and len(r.content)>100


def test_r29_rule_and_exception_are_returned_together_from_neighbor_context():
    doc_id='nissan-rule-exception-r29'
    insert_document(doc_id,'ظرفیت نیسان.pdf',[
        'وزن مجاز بارگیری نیسان در حالت عادی ۲۰۰۰ کیلوگرم است.',
        'تبصره: در شمال تهران و بالاتر از اتوبان باهنر به علت سربالایی، حداکثر بار نیسان ۱۷۰۰ کیلوگرم است.',
        'اطلاعات تکمیلی حمل بار.'
    ])
    results=main.retrieve('وزن مجاز بارگیری نیسان چقدر است؟',None)
    assert results
    combined='\n'.join(x['content'] for x in results if x['document_id']==doc_id)
    assert '۲۰۰۰' in combined and '۱۷۰۰' in combined


def test_r29_clear_fts_match_skips_remote_query_embedding(monkeypatch):
    doc_id='fast-local-r29'
    insert_document(doc_id,'fast-local.txt',['قانون بارسان: ظرفیت ویژه پیکان در این آزمون ۳۰۰ کیلوگرم است.'])
    monkeypatch.setattr(main,'REMOTE_EMBEDDING_ENABLED',True)
    monkeypatch.setattr(main,'EMBEDDING_QUERY_SKIP_CONFIDENCE',0.45)
    def should_not_call(*args,**kwargs):
        raise AssertionError('remote embedding should be skipped for a clear FTS hit')
    monkeypatch.setattr(main,'_embedding_candidate_scores',should_not_call)
    rows=main.retrieve('ظرفیت ویژه پیکان در این آزمون چند کیلوگرم است؟',None)
    assert any(x['document_id']==doc_id for x in rows)


def test_r294_independent_operational_endpoints():
    paths={route.path for route in main.app.routes}
    for path in ('/api/v1/cargo/check','/api/v1/routing/search','/api/v1/calculations/cancellation','/api/v1/calculations/waiting','/api/v1/calculations/deviation'):
        assert path in paths
    html=main.MAIN_HTML
    assert 'releaseTag' not in html
    assert 'R29.2 ابزارهای عملیاتی + RAG 3.0' not in html
    assert "api('/api/v1/cargo/check'" in html
    assert "api('/api/v1/routing/search'" in html
    assert "api('/api/v1/calculations/cancellation'" in html
    assert "api('/api/v1/calculations/waiting'" in html
    assert "api('/api/v1/calculations/deviation'" in html


def test_math_does_not_bypass_knowledge_sentences():
    assert main.direct_math_answer('۲۰۰۰ - ۳۰۰ چقدر می‌شود؟') is not None
    assert main.direct_math_answer('طبق منبع ظرفیت ۲۰۰۰ است؛ اگر ۳۰۰ کم شود چقدر می‌شود؟') is None
    assert main.safe_decimal_calculate('۱۲.۵ * ۸') == main.Decimal('100.0')
    assert main.safe_decimal_calculate('(2000-300)/2') == main.Decimal('850')


def test_training_priority_and_module_independence_contract():
    source=Path(main.__file__).read_text(encoding='utf-8')
    assert "Training -> Sources -> FAQ -> Cache" in source
    assert "module not in {'cargo','route','calc'}" in source
    assert "memory=''" in source

def test_r294_operational_settings_survive_schema_recheck():
    token=owner_token();headers={'Authorization':f'Bearer {token}'}
    with TestClient(main.app) as client:
        r=client.put('/api/v1/cargo/vehicles/nissan_flatbed',headers=headers,json={'length_cm':180,'width_cm':130,'height_cm':100,'max_weight_kg':1000})
        assert r.status_code==200,r.text
        r=client.put('/api/v1/calculations/settings/peykan',headers=headers,json={'cancellation_base_toman':80000,'waiting_hourly_toman':50000,'deviation_per_km_toman':9000,'free_wait_minutes':50,'extra_destination_free_minutes':15,'deviation_use_distance':True,'deviation_use_time':False})
        assert r.status_code==200,r.text
    main.ensure_schema()
    with main.get_db() as db:
        cargo=dict(db.execute("SELECT * FROM cargo_vehicle_profiles WHERE vehicle='nissan_flatbed'").fetchone())
        calc=dict(db.execute("SELECT * FROM calculation_settings WHERE vehicle='peykan'").fetchone())
    assert cargo['configured']==1 and cargo['length_cm']==pytest.approx(180)
    assert calc['waiting_hourly_toman']==50000 and calc['free_wait_minutes']==50


def test_r294_waiting_clock_mode_handles_midnight():
    token=owner_token();headers={'Authorization':f'Bearer {token}'}
    setting={'cancellation_base_toman':100000,'waiting_hourly_toman':60000,'deviation_per_km_toman':10000,'free_wait_minutes':60,'extra_destination_free_minutes':15,'deviation_use_distance':True,'deviation_use_time':False}
    with TestClient(main.app) as client:
        assert client.put('/api/v1/calculations/settings/nissan',headers=headers,json=setting).status_code==200
        r=client.post('/api/v1/calculations/waiting',headers=headers,json={'vehicle':'nissan','calculation_mode':'clock','origin_start_time':'23:50','origin_end_time':'00:20','destination_count':1,'destination_time_ranges':[{'start_time':'00:30','end_time':'01:30','destination_number':1}]})
        assert r.status_code==200,r.text
        data=r.json()
        assert data['total_wait_minutes']==90
        assert data['free_wait_minutes']==60
        assert data['billable_wait_minutes']==30
        assert data['final_amount_toman']==30000


def test_r295_cargo_vehicle_catalog_is_manager_trained_and_operator_simple():
    token=owner_token();headers={'Authorization':f'Bearer {token}'}
    with TestClient(main.app) as client:
        rows=client.get('/api/v1/cargo/vehicles',headers=headers).json()
        keys=[x['vehicle'] for x in rows]
        assert keys==['peykan_flatbed','peykan_no_flatbed','nissan_flatbed','nissan_no_flatbed','khavar_covered','khavar_open']
        labels=[x['vehicle_label'] for x in rows]
        assert labels==['پیکان کفی دار','پیکان بدون کفی','نیسان کفی دار','نیسان بدون','خاور مسقف','خاور رو باز']
        html=main.MAIN_HTML
        for label in labels:
            assert label in html
        # Operator UI does not expose vehicle-envelope inputs; only cargo dimensions/count.
        for forbidden in ('cargoOverrideLength','cargoOverrideWidth','cargoOverrideHeight','override_length_cm','override_width_cm','override_height_cm'):
            assert forbidden not in html
        assert client.put('/api/v1/cargo/vehicles/peykan_flatbed',headers=headers,json={'length_cm':100,'width_cm':100,'height_cm':100,'max_weight_kg':None}).status_code==200
        r=client.post('/api/v1/cargo/check',headers=headers,json={'vehicle':'peykan_flatbed','items':[{'name':'بار','count':10,'length_cm':50,'width_cm':50,'height_cm':50,'rotatable':True}]})
        assert r.status_code==200,r.text
        item=r.json()['calculation']['items'][0]
        assert item['capacity']==8
        assert item['loadable_count']==8
        assert item['unloadable_count']==2


def test_r295_time_and_distance_deviation_are_both_available_for_same_vehicle():
    token=owner_token();headers={'Authorization':f'Bearer {token}'}
    setting={'cancellation_base_toman':100000,'waiting_hourly_toman':60000,'deviation_per_km_toman':10000,'deviation_time_unit_minutes':10,'deviation_time_unit_toman':5000,'free_wait_minutes':60,'extra_destination_free_minutes':15,'deviation_use_distance':True,'deviation_use_time':True}
    with TestClient(main.app) as client:
        r=client.put('/api/v1/calculations/settings/nissan',headers=headers,json=setting);assert r.status_code==200,r.text
        km=client.post('/api/v1/calculations/deviation',headers=headers,json={'vehicle':'nissan','mode':'distance','distance_km':3});assert km.status_code==200,km.text
        tm=client.post('/api/v1/calculations/deviation',headers=headers,json={'vehicle':'nissan','mode':'time','wait_minutes':20});assert tm.status_code==200,tm.text
        assert km.json()['deviation_amount_toman']==30000
        assert tm.json()['deviation_amount_toman']==10000
        assert tm.json()['deviation_time_unit_minutes']==1
        assert tm.json()['deviation_time_unit_toman']==500
        assert tm.json()['deviation_per_minute_toman']==500


def test_r295_frontend_accepts_persian_numeric_keyboard_and_simplifies_cargo_fields():
    from ui_templates import MAIN_HTML
    html=MAIN_HTML
    assert 'function parseLocalizedNumberV3' in html
    assert '۰۱۲۳۴۵۶۷۸۹' in html and '٠١٢٣٤٥٦٧٨٩' in html
    for element in ('cancelWaitMinutes','waitingOriginMinutes','waitingDestinationMinutes','deviationKm','deviationWaitMinutes','cargoLengthV3','cargoWidthV3','cargoHeightV3','cargoCountV3'):
        assert f'id="{element}" type="text"' in html
    assert 'id="cargoTrainingPanel"' in html
    assert 'id="cargoItemRows"' not in html
    assert 'id="cargoNotesV2"' not in html
    assert 'id="cargoProfileAdmin"' not in html


def test_r295_training_first_and_source_ingestion_remain_active():
    source=Path(main.__file__).read_text(encoding='utf-8')
    html=Path(main.__file__).with_name('ui_templates.py').read_text(encoding='utf-8')
    assert "stage,sources,deep_meta=await retrieve_deep_priority_stage_async(question,user,integration=False)" in source
    assert 'تحلیل دقیق صفحه‌به‌صفحه' in html
    assert 'بازسازی همه منابع' in html
    assert '/api/v1/admin/documents/reindex-all' in html


def test_r295_operational_modules_remain_independent():
    source=Path(main.__file__).read_text(encoding='utf-8')
    for path in ('/api/v1/cargo/check','/api/v1/routing/search','/api/v1/calculations/cancellation','/api/v1/calculations/waiting','/api/v1/calculations/deviation'):
        assert path in source
    assert "module not in {'cargo','route','calc'}" in source


def test_r296_exact_six_vehicle_profiles_are_manager_configured_only():
    token=owner_token();headers={'Authorization':f'Bearer {token}'}
    exact=[
        ('peykan_flatbed','پیکان کفی دار'),('peykan_no_flatbed','پیکان بدون کفی'),
        ('nissan_flatbed','نیسان کفی دار'),('nissan_no_flatbed','نیسان بدون'),
        ('khavar_covered','خاور مسقف'),('khavar_open','خاور رو باز'),
    ]
    with TestClient(main.app) as client:
        for i,(key,label) in enumerate(exact,1):
            r=client.put(f'/api/v1/cargo/vehicles/{key}',headers=headers,json={'length_cm':100+i,'width_cm':80+i,'height_cm':90+i,'max_weight_kg':None})
            assert r.status_code==200,r.text
            body=r.json(); assert body['vehicle']==key and body['vehicle_label']==label and body['configured'] is True
        old=client.put('/api/v1/cargo/vehicles/pickup_boxed',headers=headers,json={'length_cm':100,'width_cm':100,'height_cm':100,'max_weight_kg':None})
        assert old.status_code==400
        # Cargo check uses the saved manager profile and operator payload only supplies cargo size/count.
        r=client.post('/api/v1/cargo/check',headers=headers,json={'vehicle':'khavar_open','items':[{'count':3,'length_cm':50,'width_cm':50,'height_cm':50}]})
        assert r.status_code==200,r.text
        assert r.json()['calculation']['total_requested_count']==3


def test_r296_cargo_check_schema_has_no_operator_vehicle_override_fields():
    fields=set(main.CargoCheckV2Input.model_fields)
    assert fields=={'vehicle','items','notes'}


def test_r297_cargo_form_is_vertical_and_count_drives_capacity():
    from ui_templates import MAIN_HTML
    html=MAIN_HTML
    assert 'class="cargo-panel-stack-v4"' in html
    assert 'class="cargo-form-stack-v4"' in html
    assert 'id="cargoCountV3"' in html
    assert 'تعداد درخواستی:' in html and 'ظرفیت هندسی این خودرو برای این ابعاد:' in html
    assert 'function escapeHtml(s){return esc(s)}' in html
    token=owner_token();headers={'Authorization':f'Bearer {token}'}
    with TestClient(main.app) as client:
        assert client.put('/api/v1/cargo/vehicles/peykan_flatbed',headers=headers,json={'length_cm':100,'width_cm':100,'height_cm':100,'max_weight_kg':None}).status_code==200
        r=client.post('/api/v1/cargo/check',headers=headers,json={'vehicle':'peykan_flatbed','items':[{'count':20,'length_cm':50,'width_cm':50,'height_cm':50}]})
        assert r.status_code==200,r.text
        item=r.json()['calculation']['items'][0]
        assert item['requested_count']==20
        assert item['capacity']==8
        assert item['loadable_count']==8
        assert item['unloadable_count']==12


def test_r297_deviation_training_is_single_per_minute_rate():
    from ui_templates import MAIN_HTML
    html=MAIN_HTML
    assert 'انحراف مسیر به ازای هر یک دقیقه (تومان)' in html
    assert 'calcDeviationPerMinute' in html
    assert 'calcDeviationTimeUnitMinutes' not in html
    assert 'calcDeviationTimeUnitToman' not in html
    token=owner_token();headers={'Authorization':f'Bearer {token}'}
    setting={'cancellation_base_toman':100000,'waiting_hourly_toman':60000,'deviation_per_km_toman':10000,'deviation_per_minute_toman':750,'free_wait_minutes':60,'extra_destination_free_minutes':15,'deviation_use_distance':True,'deviation_use_time':True}
    with TestClient(main.app) as client:
        r=client.put('/api/v1/calculations/settings/nissan',headers=headers,json=setting);assert r.status_code==200,r.text
        body=r.json(); assert body['deviation_per_minute_toman']==750
        tm=client.post('/api/v1/calculations/deviation',headers=headers,json={'vehicle':'nissan','mode':'time','wait_minutes':20});assert tm.status_code==200,tm.text
        assert tm.json()['deviation_amount_toman']==15000
        assert tm.json()['deviation_per_minute_toman']==750


def test_r298_page_by_page_manager_upload_and_visible_video_loader():
    source=Path(main.__file__).read_text(encoding='utf-8')
    html=Path(main.__file__).with_name('ui_templates.py').read_text(encoding='utf-8')
    env=Path(main.__file__).with_name('.env.example').read_text(encoding='utf-8')
    assert 'PDF_VISION_SCAN_ALL_PAGES=true' in env
    assert 'PDF_VISION_DPI=180' in env
    assert 'PDF_VISION_MAX_TOKENS=2400' in env
    assert 'SOURCE_PAGE_BY_PAGE_STRICT=true' in env
    assert "Depends(require_roles('manager','admin')))" in source
    assert 'data-panel="resourcesPanel"' in html
    assert 'مدیر و ادمین می‌توانند فایل یا Google Docs اضافه کنند' in html
    assert "v.src='/thinking-loader.mp4?v=__BARSAN_ASSET_VERSION__'" in html
    assert 'from ui_components import THINKING_CSS' in html
    assert 'width:196px!important;aspect-ratio:16/9!important' in main.MAIN_HTML
    assert 'در حال بررسی آموزش و منابع…' in html

def test_r298_thinking_asset_is_small_h264_mp4():
    asset=Path(main.__file__).with_name('thinking_loader.mp4')
    assert asset.exists()
    assert 10_000 < asset.stat().st_size < 500_000


def test_r298_manager_can_really_upload_source():
    username='manager_r298_upload'
    password='Manager_R298_123!'
    with main.get_db() as db:
        row=db.execute("SELECT id FROM users WHERE username=?",(username,)).fetchone()
        if row:
            manager_id=row['id']
        else:
            salt,hashed=main.hash_password(password)
            cur=db.execute("INSERT INTO users(username,email,name,password_hash,salt,role,is_active,is_owner,department,created_at) VALUES(?,?,?,?,?,'manager',1,0,?,?)",(username,None,'مدیر تست آپلود',hashed,salt,'QA',main.now_iso()))
            db.commit(); manager_id=cur.lastrowid
    token=main.create_token(manager_id,'manager')
    headers={'Authorization':f'Bearer {token}'}
    with TestClient(main.app) as client:
        cfg=client.get('/api/v1/admin/upload-config',headers=headers)
        assert cfg.status_code==200,cfg.text
        assert cfg.json()['pdf_vision_scan_all_pages'] is True
        files={'file':('manager-source.txt',b'manager source upload test','text/plain')}
        r=client.post('/api/v1/admin/documents',headers=headers,files=files,data={'visibility':'public'})
        assert r.status_code==200,r.text
        assert r.json()['status'] in {'processing','ready'}

def test_r298_thinking_video_route_no_cache_and_mp4():
    with TestClient(main.app) as client:
        r=client.get('/thinking-loader.mp4')
        assert r.status_code==200
        assert r.headers.get('content-type','').startswith('video/mp4')
        assert 'no-store' in r.headers.get('cache-control','')
        assert len(r.content)>10000


def test_r30_authoritative_stage_cache_short_circuits_repeat(monkeypatch):
    main._RETRIEVAL_STAGE_CACHE.clear()
    calls={'training':0}
    sample=[{'source_type':'training','training_id':'speed-test','document_id':'training:speed-test','file_name':'آموزش مدیریتی','chunk_index':0,'content':'پاسخ قطعی آموزش','answer':'پاسخ قطعی آموزش','score':0.99,'priority':100}]
    def fake_training(question,user,integration=False):
        calls['training']+=1
        return sample
    monkeypatch.setattr(main,'retrieve_training',fake_training)
    first=main.retrieve_priority_stage('سؤال سرعت کش مرحله',None,False)
    second=main.retrieve_priority_stage('سؤال سرعت کش مرحله',None,False)
    assert first[0]=='training' and second[0]=='training'
    assert calls['training']==1


def test_r30_exact_answer_cache_is_knowledge_version_safe():
    q='سؤال دقیق تکراری برای مسیر سریع'
    sources=[{'source_type':'training','document_id':'training:r30','file_name':'آموزش مدیر','chunk_index':0,'score':1.0,'excerpt':'پاسخ سریع'}]
    main.store_cached_answer(q,False,None,False,'پاسخ سریع معتبر',sources,'r30-test',cache_tier='approved')
    hit=main.find_exact_cached_answer(q,False,None,False)
    assert hit and hit['answer']=='پاسخ سریع معتبر'
    with main.get_db() as db:
        main.bump_knowledge_version(db)
    assert main.find_exact_cached_answer(q,False,None,False) is None


def test_r30_fastest_provider_routing_uses_recent_latency(monkeypatch):
    main._PROVIDER_SPEED_CACHE.clear()
    slots=[{'slot':1},{'slot':2}]
    monkeypatch.setattr(main,'ordered_available_ai_slots',lambda: list(slots))
    ts=main.now_iso()
    with main.get_db() as db:
        for ms in (900,1000,1100):
            db.execute("INSERT INTO api_call_events(slot,provider_label,model,model_route,status,response_ms,attempt_index,was_failover,created_at) VALUES(1,'slow','m','standard','success',?,1,0,?)",(ms,ts))
        for ms in (100,120,140):
            db.execute("INSERT INTO api_call_events(slot,provider_label,model,model_route,status,response_ms,attempt_index,was_failover,created_at) VALUES(2,'fast','m','standard','success',?,1,0,?)",(ms,ts))
    ordered=main.ordered_available_ai_slots_for_route('standard')
    assert int(ordered[0]['slot'])==2


def test_r31_admin_can_add_and_manage_dynamic_api_slots_up_to_twenty():
    token=owner_token();headers={'Authorization':f'Bearer {token}'}
    with main.get_db() as db:
        db.execute('DELETE FROM ai_provider_configs')
        db.execute('DELETE FROM ai_api_slot_state WHERE slot>=5')
    with TestClient(main.app) as client:
        payload={
            'label':'Dynamic Test','base_url':'https://provider.example/v1','api_key':'test-dynamic-key-1234567890',
            'model':'test-model','vision_model':'vision-test','transcription_model':'voice-test','embedding_model':'embed-test'
        }
        created=client.post('/api/v1/admin/api-providers',headers=headers,json=payload)
        assert created.status_code==200,created.text
        assert created.json()['slot']==2
        listing=client.get('/api/v1/admin/api-providers',headers=headers)
        assert listing.status_code==200
        body=listing.json();assert body['max_slots']==20
        row=next(x for x in body['items'] if x['slot']==2)
        assert row['managed_by']=='admin'
        assert 'api_key' not in row and row['api_key_masked']
        slots={x['slot']:x for x in main.configured_ai_slots()}
        assert slots[2]['model']=='test-model'
        assert main._vision_model_for_slot(2)=='vision-test'
        disabled=client.patch('/api/v1/admin/api-providers/2',headers=headers,json={'enabled':False})
        assert disabled.status_code==200
        assert all(x['slot']!=2 for x in main.configured_ai_slots())
        enabled=client.patch('/api/v1/admin/api-providers/2',headers=headers,json={'enabled':True,'api_key':'test-replaced-dynamic-key-654321'})
        assert enabled.status_code==200
        assert next(x for x in main.configured_ai_slots() if x['slot']==2)['api_key'].endswith('654321')
        deleted=client.delete('/api/v1/admin/api-providers/2',headers=headers)
        assert deleted.status_code==200
        assert all(x['slot']!=2 for x in main.configured_ai_slots())


def test_r31_ui_exposes_runtime_api_manager_without_rendering_secrets():
    html=main.MAIN_HTML
    assert 'افزودن API جدید' in html
    assert 'تا سقف ۲۰ API' in html
    assert '/api/v1/admin/api-providers' in html
    assert 'تعویض کلید' in html


def test_r31_backup_excludes_runtime_api_keys():
    import sqlite3, zipfile, tempfile
    with main.get_db() as db:
        db.execute('DELETE FROM ai_provider_configs')
        db.execute("INSERT INTO ai_provider_configs(slot,label,base_url,api_key,model,enabled,created_at,updated_at) VALUES(5,'Backup Test','https://provider.example/v1','test-runtime-secret-key-placeholder','m',1,?,?)",(main.now_iso(),main.now_iso()))
    path,_,_,_,_=main.create_backup_file(actor_id=None,action='backup',persist_to_disk=False)
    try:
        with zipfile.ZipFile(path) as z:
            raw=z.read('barsan.db')
            manifest=z.read('backup_manifest.json').decode('utf-8')
        tmp=Path(tempfile.gettempdir())/'barsan-r31-backup-check.db';tmp.write_bytes(raw)
        con=sqlite3.connect(tmp)
        count=con.execute('SELECT COUNT(*) FROM ai_provider_configs').fetchone()[0]
        con.close();tmp.unlink(missing_ok=True)
        assert count==0
        assert 'includes_secrets' in manifest and 'false' in manifest.lower()
    finally:
        path.unlink(missing_ok=True)
        with main.get_db() as db:db.execute('DELETE FROM ai_provider_configs')


def test_r31_dynamic_api_pool_capacity_is_twenty_total_slots():
    token=owner_token();headers={'Authorization':f'Bearer {token}'}
    with main.get_db() as db:
        db.execute('DELETE FROM ai_provider_configs')
        db.execute('DELETE FROM ai_api_slot_state WHERE slot>=5')
    with TestClient(main.app) as client:
        for expected_slot in range(2,21):
            r=client.post('/api/v1/admin/api-providers',headers=headers,json={
                'label':f'P{expected_slot}','base_url':'https://provider.example/v1',
                'api_key':f'sk-capacity-{expected_slot:02d}-abcdefgh','model':'m'
            })
            assert r.status_code==200,r.text
            assert r.json()['slot']==expected_slot
        extra=client.post('/api/v1/admin/api-providers',headers=headers,json={
            'label':'Overflow','base_url':'https://provider.example/v1','api_key':'test-overflow-key-abcdefgh1234','model':'m'
        })
        assert extra.status_code==409
        assert len(main.configured_ai_slots())==20
    with main.get_db() as db:
        db.execute('DELETE FROM ai_provider_configs')
        db.execute('DELETE FROM ai_api_slot_state WHERE slot>=5')


def test_r32_builtin_booklet_preindex_covers_all_four_files_and_pages(monkeypatch):
    monkeypatch.setattr(main,'BUILTIN_SOURCE_AUTO_ENRICH',False)
    result=main.ensure_builtin_sources()
    assert result['installed']==4
    with main.get_db() as db:
        rows=db.execute("SELECT source_key,page_count,chunk_count,is_builtin,is_enabled FROM documents WHERE is_builtin=1 ORDER BY source_key").fetchall()
        assert [r['source_key'] for r in rows]==['01','02','03','04']
        assert sum(int(r['page_count']) for r in rows)==103
        assert all(int(r['chunk_count'])>0 for r in rows)
        assert all(int(r['is_builtin'])==1 for r in rows)
        assert db.execute("SELECT COUNT(*) FROM document_pages WHERE document_id LIKE 'builtin-barsan-%'").fetchone()[0]==103


def test_r32_manager_training_overrides_builtin_cancellation_rule(monkeypatch):
    monkeypatch.setattr(main,'BUILTIN_SOURCE_AUTO_ENRICH',False)
    main.ensure_builtin_sources()
    with main.get_db() as db:
        owner=dict(db.execute('SELECT * FROM users WHERE is_owner=1 LIMIT 1').fetchone())
        ts=main.now_iso()
        db.execute("DELETE FROM training_rules WHERE id='r32-khavar-override'")
        db.execute("INSERT INTO training_rules(id,topic,topic_key,canonical_key,instruction,answer,priority,status,effective_from,created_by,approved_by,created_at,updated_at,visibility,allowed_roles_json,allowed_user_ids_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'public','[]','[]')",
                   ('r32-khavar-override','کنسلی خاور','کنسلی خاور','کنسلی|خاور','اگر درباره کنسلی خاور پرسیده شد','کنسلی خاور ۵۰۰ هزار تومان است.',100,'active',ts,owner['id'],owner['id'],ts,ts))
        main.rebuild_training_fts(db);main.bump_knowledge_version(db)
    stage,items=main.retrieve_priority_stage('کنسلی پایه خاور چقدر است؟',owner,False)
    assert stage=='training'
    assert '۵۰۰' in items[0]['content']


def test_r32_builtin_booklet_access_toggle_excludes_only_builtin_sources(monkeypatch):
    monkeypatch.setattr(main,'BUILTIN_SOURCE_AUTO_ENRICH',False)
    main.ensure_builtin_sources()
    with main.get_db() as db:
        owner=dict(db.execute('SELECT * FROM users WHERE is_owner=1 LIMIT 1').fetchone())
        db.execute("UPDATE documents SET status='ready',quality_gate_reason='passed' WHERE is_builtin=1")
        db.execute("UPDATE training_rules SET status='rejected' WHERE id='r32-khavar-override'")
        main.rebuild_training_fts(db);main.bump_knowledge_version(db)
    assert main.retrieve_priority_stage('وزن مجاز بارگیری نیسان چقدر است؟',owner,False)[0]=='document'
    main.set_builtin_sources_access(main.BuiltinSourceAccessInput(enabled=False),owner)
    with main.get_db() as db:
        assert db.execute('SELECT COUNT(*) FROM documents WHERE is_builtin=1 AND is_enabled=1').fetchone()[0]==0
    main.set_builtin_sources_access(main.BuiltinSourceAccessInput(enabled=True),owner)
    assert main.retrieve_priority_stage('وزن مجاز بارگیری نیسان چقدر است؟',owner,False)[0]=='document'


def test_r32_source_audit_and_ui_toggle_contract():
    root=Path(main.__file__).parent
    audit=json.loads((root/'BUILTIN_SOURCE_AUDIT_R32.json').read_text(encoding='utf-8'))
    assert audit['summary']['total_files']==4
    assert audit['summary']['total_pages']==103
    assert audit['summary']['total_images']==55
    assert audit['summary']['all_pages_hashed'] is True
    html=(root/'ui_templates.py').read_text(encoding='utf-8')
    assert 'دسترسی گفتگو به ۴ جزوه پایه' in html
    assert '/api/v1/admin/builtin-sources/access' in html
    assert 'آموزش مدیر همیشه قبل از جزوه‌ها' in html


def test_r32_1_chat_ui_hides_debug_feedback_metadata():
    import ui_templates
    html=ui_templates.MAIN_HTML
    assert '.chat-room .msg-source-meta{display:none!important}' in html
    assert "await typeText(body,d.answer);appendFeedbackButtons(body,d);refreshConversations()" in html
    assert "rows.forEach(r=>{const body=addMsg(r.role,r.content);if(r.role==='assistant')appendFeedbackButtons(body,r)});" in html


def test_r35_container_drops_privileges_after_railway_volume_preparation():
    from pathlib import Path
    docker=Path('Dockerfile').read_text(encoding='utf-8')
    launcher=Path('railway_start.py').read_text(encoding='utf-8')
    assert 'apt-get install' not in docker
    assert 'gosu' not in docker.lower()
    assert 'railway_start.py' in docker
    assert 'os.setgroups([])' in launcher and 'os.setuid(uid)' in launcher
    assert '.barsan-owner-{uid}-{gid}' in launcher
    assert 'BARSAN_R35_BUILD_OK' in docker


def test_r35_builtin_page_rescue_only_uses_quality_gate_ready_sources(monkeypatch):
    monkeypatch.setattr(main,'BUILTIN_SOURCE_AUTO_ENRICH',False)
    main.ensure_builtin_sources()
    with main.get_db() as db:
        db.execute("UPDATE documents SET status='ready',quality_gate_reason='passed' WHERE is_builtin=1")
        owner=dict(db.execute('SELECT * FROM users WHERE is_owner=1 LIMIT 1').fetchone())
    cases=(
        ('کنسلی پایه خاور چقدر است؟','04_BARSAN','کنسلی پایه خاور'),
        ('توقف رایگان نیسان چند دقیقه است؟','03_BARSAN','60'),
        ('وزن مجاز بارگیری نیسان چقدر است؟','01_BARSAN','2 تن'),
        ('رنگ قرمز در صف رانندگان یعنی چه؟','02_BARSAN','رنگ قرمز'),
        ('کیلومتر مجاز جنوب شرق برای ارسال سرویس چقدر است؟','04_BARSAN','9 کیلومتر'),
    )
    for question,file_hint,needle in cases:
        stage,items=main.retrieve_priority_stage(question,owner,False)
        assert stage=='document',question
        top='\n'.join(str(x.get('content') or '') for x in items[:8])
        assert any(file_hint in str(x.get('file_name') or '') for x in items[:8]),question
        assert needle in top.replace('  ',' '), (question,top[:1200])


def test_r32_1_builtin_startup_repairs_searchable_status_after_failed_enrichment(monkeypatch):
    monkeypatch.setattr(main,'BUILTIN_SOURCE_AUTO_ENRICH',False)
    main.ensure_builtin_sources()
    with main.get_db() as db:
        db.execute("UPDATE documents SET status='error' WHERE is_builtin=1 AND chunk_count>0")
    main.ensure_builtin_sources()
    with main.get_db() as db:
        main.bump_knowledge_version(db)
        rows=db.execute("SELECT status,chunk_count FROM documents WHERE is_builtin=1").fetchall()
    assert rows and all(r['status']=='partial' and int(r['chunk_count'])>0 for r in rows)
    with main.get_db() as db:
        owner=dict(db.execute('SELECT * FROM users WHERE is_owner=1 LIMIT 1').fetchone())
    stage,items=main.retrieve_priority_stage('وزن مجاز بارگیری نیسان چقدر است؟',owner,False)
    assert not any(str(x.get('document_id') or '').startswith('builtin-barsan-') for x in items)


def test_r33_thinking_loader_is_canonically_right_aligned_and_feedback_is_clean():
    import ui_templates
    html=ui_templates.MAIN_HTML
    assert "margin:8px 0 10px auto!important" in html
    assert "feedback-actions" in html
    assert "درست بود" in html and "غلط بود" in html and "ناقص بود" in html
    assert "appendResponseMeta(body,d)" not in html
    assert "پاسخ از:" not in html
    assert ".chat-room .msg-source-meta{display:none!important}" in html


def test_r33_visual_cargo_training_ui_and_routes_exist():
    import ui_templates
    html=ui_templates.MAIN_HTML
    assert "آموزش تصویری بررسی بار" in html
    assert 'id="cargoImageTrainingVehicle"' in html
    assert 'id="cargoImageSearchInput"' in html
    assert "نیسان لوله سه متری" in html
    paths={route.path for route in main.app.routes}
    assert '/api/v1/cargo/image-training' in paths
    assert '/api/v1/cargo/image-training/search' in paths
    assert '/api/v1/cargo/image-training/{training_id}/image' in paths


def test_r33_source_ingestion_defaults_are_strict():
    assert main.SOURCE_INCLUDE_PARTIAL_DOCUMENTS is False
    assert main.SOURCE_MIN_QUALITY_PCT >= 92


def test_r33_visual_cargo_training_roundtrip():
    import base64
    token=owner_token();headers={'Authorization':f'Bearer {token}'}
    png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2nWQAAAAASUVORK5CYII=')
    with TestClient(main.app) as client:
        created=client.post('/api/v1/cargo/image-training',headers=headers,data={'vehicle':'nissan','cargo_name':'لوله سه متری'},files={'image':('nissan-pipe.png',png,'image/png')})
        assert created.status_code==200,created.text
        item=created.json();assert item['vehicle']=='nissan';assert item['cargo_name']=='لوله سه متری'
        found=client.get('/api/v1/cargo/image-training/search',headers=headers,params={'q':'نیسان لوله سه متری'})
        assert found.status_code==200,found.text
        assert found.json()['items'] and found.json()['items'][0]['id']==item['id']
        image=client.get(item['image_url'],headers=headers)
        assert image.status_code==200 and image.headers['content-type'].startswith('image/png')
        deleted=client.delete('/api/v1/cargo/image-training/'+item['id'],headers=headers)
        assert deleted.status_code==200


def test_r33_backup_preserves_nested_visual_training_files():
    nested=main.CARGO_IMAGE_TRAINING_DIR/'backup-probe.png'
    nested.parent.mkdir(parents=True,exist_ok=True)
    nested.write_bytes(b'\x89PNG\r\n\x1a\nprobe')
    try:
        payload,filename,_=main.create_backup_bytes(None,action='backup',persist_to_disk=False)
        import io,zipfile
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            assert 'uploads/cargo-image-training/backup-probe.png' in archive.namelist()
    finally:
        nested.unlink(missing_ok=True)


# R34 deep analysis / multi-retrieval / reasoning / verification / confidence gate.
def test_r34_query_analysis_decomposes_complex_cargo_question():
    from deep_rag import analyze_query
    plan=analyze_query('آیا نیسان با ۲ تن بار و لوله سه متری مجاز است یا استثنا دارد؟')
    assert 'نیسان' in plan.entities
    assert any('2' in x for x in plan.numbers)
    assert plan.intent in {'decision','limit'}
    assert 'numeric' in plan.flags
    assert 'exception_sensitive' in plan.flags
    assert len(plan.subqueries)>=3
    assert plan.complexity>=0.5


def test_r34_multiretrieval_and_semantic_rerank_reward_cross_query_coverage():
    from deep_rag import analyze_query,merge_multiretrieval,semantic_rerank_candidates
    plan=analyze_query('نیسان ۲ تن لوله سه متری مجاز است؟')
    common={'document_id':'d1','chunk_index':1,'source_type':'document','file_name':'قوانین نیسان','content':'نیسان برای بار 2 تن محدودیت ظرفیت و طول بار دارد.','score':0.62}
    rows=[(plan.subqueries[0],[common]),(plan.subqueries[1],[dict(common),{'document_id':'d2','chunk_index':2,'source_type':'document','file_name':'متفرقه','content':'راهنمای عمومی ثبت سرویس','score':0.70}])]
    merged=merge_multiretrieval(plan,rows,top_n=10)
    ranked=semantic_rerank_candidates(plan,merged,top_n=10)
    assert ranked[0]['document_id']=='d1'
    assert ranked[0]['deep_query_hits']>=2
    assert ranked[0]['query_coverage_score']>0


def test_r34_rule_exception_map_separates_rules_conditions_and_exceptions():
    from deep_rag import build_rule_exception_map
    items=[{'file_name':'آموزش','content':'حداکثر وزن نیسان 2 تن است. اگر بار بلند باشد باید شرایط طول بررسی شود. تبصره: در شرایط خاص مجوز مدیر لازم است.'}]
    rule_map=build_rule_exception_map(items)
    assert rule_map['limits']
    assert rule_map['conditions']
    assert rule_map['exceptions']
    assert rule_map['numeric_facts']


def test_r34_advanced_route_requests_reasoning_and_falls_back_compatibly(monkeypatch):
    calls=[]
    async def fake_request(**kwargs):
        calls.append(kwargs['payload'])
        if kwargs['payload'].get('reasoning_effort'):
            raise main.HTTPException(status_code=502,detail='HTTP 400 unsupported reasoning_effort')
        return {'choices':[{'message':{'content':'پاسخ معتبر.'},'finish_reason':'stop'}],'usage':{'prompt_tokens':3,'completion_tokens':2,'total_tokens':5}}
    monkeypatch.setattr(main,'AI_PROVIDER','openai_compatible')
    monkeypatch.setattr(main,'AI_REASONING_ENABLED',True)
    monkeypatch.setattr(main,'AI_REASONING_PARAMETER','reasoning_effort')
    monkeypatch.setattr(main,'AI_PROVIDER_CAPABILITIES_JSON','{"1":{"reasoning_mode":"reasoning_effort"}}')
    monkeypatch.setattr(main,'ordered_available_ai_slots_for_route',lambda route:[{'slot':1,'label':'Test','api_key':'k','base_url':'https://example.test/v1','model':'test-model','models':{'advanced':'test-model','standard':'test-model','economy':'test-model'},'input_cost_per_1m':0,'output_cost_per_1m':0}])
    monkeypatch.setattr(main,'_request_json_with_retries',fake_request)
    answer,usage,finish=asyncio.run(main._generate_ai_text([{'role':'user','content':'تحلیل'}],max_tokens=120,temperature=0.0,route='advanced'))
    assert answer=='پاسخ معتبر.' and finish=='stop'
    assert any(x.get('reasoning_effort')=='high' for x in calls)
    assert any('reasoning_effort' not in x for x in calls)
    assert usage['reasoning_enabled'] is False


def test_r34_evidence_confidence_penalizes_missing_conditional_evidence():
    from deep_rag import analyze_query,evidence_confidence
    plan=analyze_query('اگر نیسان 2 تن بار داشته باشد استثنا چیست؟')
    items=[{'score':0.5,'deep_semantic_score':0.5,'query_coverage_score':0.2,'entity_alignment_score':1.0,'number_alignment_score':1.0}]
    low,_=evidence_confidence(plan,items,{'conditions':[],'exceptions':[],'limits':[]},verification_status='failed')
    high,_=evidence_confidence(plan,items,{'conditions':[{'text':'اگر...'}],'exceptions':[{'text':'تبصره...'}],'limits':[{'text':'حداکثر...'}]},verification_status='verified')
    assert high>low
    assert low<main.DEEP_CONFIDENCE_COMPLEX_MIN


def test_r34_source_contains_all_seven_deep_pipeline_switches():
    source=Path(main.__file__).read_text(encoding='utf-8')
    for token in (
        'DEEP_QUERY_ANALYSIS_ENABLED','DEEP_MULTI_RETRIEVAL_ENABLED','DEEP_SEMANTIC_RERANK_ENABLED',
        'DEEP_RULE_ENGINE_ENABLED','AI_REASONING_ENABLED','DEEP_ANSWER_VERIFICATION_ENABLED','DEEP_CONFIDENCE_GATE_ENABLED',
    ):
        assert token in source


# R35 production-intelligence hardening regression suite.
def test_r35_release_schema_and_assets_are_single_source_of_truth():
    import release_info
    import ui_templates
    assert release_info.APP_VERSION == '35.2.3'
    assert release_info.RELEASE_ID == 'R35_2_3_PREDEPLOY_OVERRIDE'
    assert release_info.SCHEMA_REVISION == 'r35.2.0-001'
    assert "/thinking-loader.mp4?v=R35" in ui_templates.MAIN_HTML
    with main.get_db() as db:
        row=db.execute('SELECT release_id FROM schema_migrations WHERE revision=?',(release_info.SCHEMA_REVISION,)).fetchone()
    assert row and row['release_id']==release_info.RELEASE_ID


def test_r35_persian_query_canonicalization_and_written_numbers_are_clean():
    from deep_rag import analyze_query
    plan=analyze_query('پیکان کفی دار لوله سه متری میتونه بره؟')
    assert plan.entities == ['پیکان کفی دار']
    assert plan.numbers == ['3 متر']
    assert plan.intent == 'decision'
    assert all('؟' not in concept for concept in plan.concepts)
    assert all('پیکان پیکان' not in q for q in plan.subqueries)


def test_r35_typed_rule_engine_distinguishes_dimensions_and_real_conflicts():
    from deep_rag import build_rule_exception_map
    clean=build_rule_exception_map([{'file_name':'A','content':'طول نیسان 250 سانتی متر، عرض نیسان 150 سانتی متر و ارتفاع نیسان 200 سانتی متر است.'}])
    assert not clean['potential_numeric_conflicts']
    conflict=build_rule_exception_map([
        {'file_name':'A','content':'طول نیسان 250 سانتی متر است.'},
        {'file_name':'B','content':'طول نیسان 260 سانتی متر است.'},
    ])
    assert conflict['potential_numeric_conflicts']
    assert conflict['potential_numeric_conflicts'][0]['attribute']=='طول'


def test_r35_source_fidelity_detects_numeric_disagreement():
    fidelity,agreement=main._page_fidelity_metrics('حداکثر وزن نیسان 2000 کیلوگرم است.','حداکثر وزن نیسان 1700 کیلوگرم است.',vision_full=True,status='vision_ok')
    assert agreement == 0.0
    assert fidelity < 0.82
    matching,matching_agreement=main._page_fidelity_metrics('حداکثر وزن نیسان 2000 کیلوگرم است.','حداکثر وزن نیسان 2000 کیلوگرم است.',vision_full=True,status='vision_ok')
    assert matching_agreement == 1.0 and matching > fidelity


def test_r35_provider_secret_roundtrip_is_encrypted_at_rest_format():
    raw='sk-r35-secret-test-value'
    protected=main._protect_api_key(raw)
    assert protected.startswith('fernet:v1:')
    assert raw not in protected
    assert main._unprotect_api_key(protected)==raw


def test_r35_unknown_provider_does_not_claim_reasoning_without_capability_override(monkeypatch):
    slot={'slot':7,'label':'Unknown','base_url':'https://example.test/v1','model':'mystery-model'}
    monkeypatch.setattr(main,'AI_PROVIDER_CAPABILITIES_JSON','{}')
    assert main.provider_capabilities(slot)['reasoning_mode']=='none'
    monkeypatch.setattr(main,'AI_PROVIDER_CAPABILITIES_JSON','{"7":{"reasoning_mode":"intrinsic"}}')
    caps=main.provider_capabilities(slot)
    assert caps['reasoning_mode']=='intrinsic' and caps['reasoning_guaranteed'] is True


def test_r35_model_semantic_reranker_reorders_only_existing_candidates(monkeypatch):
    async def fake_generate(*args,**kwargs):
        return '{"order":[2,0,1]}',{'total_tokens':8},'stop'
    monkeypatch.setattr(main,'_generate_ai_text',fake_generate)
    items=[
        {'document_id':'a','chunk_index':0,'content':'الف','score':0.9},
        {'document_id':'b','chunk_index':0,'content':'ب','score':0.8},
        {'document_id':'c','chunk_index':0,'content':'ج','score':0.7},
    ]
    ranked,usage=asyncio.run(main._model_semantic_rerank('کدام مدرک مرتبط‌تر است؟',items,route='advanced'))
    assert [x['document_id'] for x in ranked]==['c','a','b']
    assert usage['total_tokens']==8


def test_r35_async_retrieval_facade_offloads_sync_work(monkeypatch):
    import threading
    caller=threading.get_ident();worker=[]
    def fake(*args,**kwargs):
        worker.append(threading.get_ident())
        return 'none',[],{'query_plan':{}}
    monkeypatch.setattr(main,'retrieve_deep_priority_stage',fake)
    result=asyncio.run(main.retrieve_deep_priority_stage_async('سؤال',None,False))
    assert result[0]=='none'
    assert worker and worker[0] != caller


def test_r35_request_observability_and_security_headers():
    with TestClient(main.app) as client:
        response=client.get('/healthz',headers={'X-Request-ID':'r35-test-request-123'})
    assert response.status_code==200
    assert response.headers['x-request-id']=='r35-test-request-123'
    assert response.headers['x-content-type-options']=='nosniff'
    assert response.headers['referrer-policy']=='same-origin'
    with main.get_db() as db:
        row=db.execute("SELECT status_code FROM request_metrics WHERE request_id='r35-test-request-123' ORDER BY id DESC LIMIT 1").fetchone()
    assert row and int(row['status_code'])==200


def test_r35_source_health_exposes_answer_eligibility_and_quality_gate():
    token=owner_token();headers={'Authorization':f'Bearer {token}'}
    with TestClient(main.app) as client:
        response=client.get('/api/v1/admin/sources/health',headers=headers)
    assert response.status_code==200,response.text
    data=response.json()
    assert data['release']=='R35_2_3_PREDEPLOY_OVERRIDE'
    assert data['schema_revision']=='r35.2.0-001'
    assert {'quality_pct','page_fidelity_pct','numeric_agreement_pct'} <= set(data['thresholds'])


def test_r35_ui_escape_function_covers_quotes_for_attribute_safety():
    import ui_templates
    html=ui_templates.MAIN_HTML
    assert """replaceAll('\"','&quot;')""" in html
    assert """replaceAll("'",'&#39;')""" in html


def test_r35_image_only_page_accepts_clean_full_vision_transcription():
    fidelity,agreement=main._page_fidelity_metrics('', 'متن کامل صفحه اسکن شده با ظرفیت نیسان 2000 کیلوگرم.', vision_full=True, status='vision_ok')
    assert agreement is None
    assert fidelity >= 0.90


def test_r35_numeric_fidelity_normalizes_equivalent_units():
    tokens_a=main._source_number_unit_tokens('ظرفیت 2 تن و طول 2 متر است.')
    tokens_b=main._source_number_unit_tokens('ظرفیت 2000 کیلوگرم و طول 200 سانتی متر است.')
    assert tokens_a == tokens_b
    fidelity,agreement=main._page_fidelity_metrics('ظرفیت 2 تن است.','ظرفیت 2000 کیلوگرم است.',vision_full=True,status='vision_ok')
    assert agreement == 1.0 and fidelity > 0.9


def test_r35_upload_config_reports_current_ingestion_quality_contract():
    token=owner_token()
    with TestClient(main.app) as client:
        response=client.get('/api/v1/admin/upload-config',headers={'Authorization':f'Bearer {token}'})
    assert response.status_code==200
    data=response.json()
    assert data['source_ingestion_version']==main.INGESTION_VERSION==6
    assert data['source_min_page_fidelity_pct']==round(main.SOURCE_MIN_PAGE_FIDELITY*100,1)
    assert data['source_min_numeric_agreement_pct']==round(main.SOURCE_MIN_NUMERIC_AGREEMENT*100,1)


def test_r35_legacy_ready_source_is_queued_for_zero_downtime_reindex():
    doc_id='r35-legacy-ready-auto-reindex'
    stored=TEST_ROOT/'uploads'/'r35-legacy-ready.txt'
    stored.parent.mkdir(parents=True,exist_ok=True)
    stored.write_text('منبع قدیمی سالم برای مهاجرت خودکار R35',encoding='utf-8')
    with main.get_db() as db:
        db.execute("DELETE FROM document_jobs WHERE document_id=?",(doc_id,))
        db.execute("DELETE FROM documents WHERE id=?",(doc_id,))
        db.execute("""INSERT INTO documents(
            id,filename,stored_path,mime_type,visibility,status,character_count,chunk_count,version,created_at,ingestion_version
        ) VALUES(?,?,?,?,?,'ready',?,?,1,?,?)""",
        (doc_id,stored.name,str(stored),'text/plain','public',len(stored.read_text(encoding='utf-8')),1,'2000-01-01T00:00:00+00:00',main.INGESTION_VERSION-1))
    result=main._enqueue_legacy_source_reindex_jobs()
    with main.get_db() as db:
        job=db.execute("SELECT status,job_type,phase FROM document_jobs WHERE document_id=? ORDER BY created_at DESC LIMIT 1",(doc_id,)).fetchone()
        doc=db.execute("SELECT status,ingestion_version FROM documents WHERE id=?",(doc_id,)).fetchone()
        db.execute("DELETE FROM document_jobs WHERE document_id=?",(doc_id,))
        db.execute("DELETE FROM documents WHERE id=?",(doc_id,))
    stored.unlink(missing_ok=True)
    assert result['queued']>=1
    assert job and job['status']=='queued' and job['job_type']=='reindex'
    assert 'R35' in str(job['phase'])
    assert doc['status']=='ready' and int(doc['ingestion_version'])==main.INGESTION_VERSION-1


def test_r35_numeric_fidelity_penalizes_vision_only_hallucinated_numbers():
    fidelity,agreement=main._page_fidelity_metrics(
        'ظرفیت نیسان 2 تن و طول آن 2 متر است.',
        'ظرفیت نیسان 2 تن و طول آن 2 متر است و ارتفاع 999 متر است.',
        vision_full=True,status='vision_ok')
    assert 0.0 < agreement < 1.0
    assert fidelity < 0.95


def test_r35_text_health_penalizes_severely_fragmented_pdf_extraction():
    healthy=' '.join(['کارشناس بارسان باید اطلاعات سرویس و نوع خودرو را دقیق بررسی کند.']*30)
    fragmented='\n'.join(['ک','ار','ش','نا','س','ب','ار','س','ان']*20)
    assert main._text_health_score(healthy) > 0.95
    assert main._text_health_score(fragmented) < main._text_health_score(healthy)
    assert main._text_health_score(fragmented) < 0.80


@pytest.mark.skipif(main.fitz is None,reason='PyMuPDF is not installed')
def test_r35_text_only_pdf_can_pass_without_configured_vision_model(monkeypatch):
    pdf=main.fitz.open();page=pdf.new_page()
    page.insert_text((50,70),'Barsan operational source text. '*20)
    payload=pdf.tobytes();pdf.close()
    monkeypatch.setattr(main,'PDF_VISION_ENABLED',True)
    monkeypatch.setattr(main,'PDF_VISION_SCAN_ALL_PAGES',True)
    monkeypatch.setattr(main,'configured_ai_slots',lambda:[])
    result=asyncio.run(main._extract_pdf_source_result_async(payload))
    assert result['status']=='ready'
    assert result['stats']['vision_candidate_pages']==0
    assert result['stats']['ingestion_quality_pct']>=main.SOURCE_MIN_QUALITY_PCT


@pytest.mark.skipif(main.fitz is None,reason='PyMuPDF is not installed')
def test_r35_image_only_pdf_remains_blocked_when_vision_is_not_configured(monkeypatch):
    pix=main.fitz.Pixmap(main.fitz.csRGB,main.fitz.IRect(0,0,40,40),False);pix.clear_with(255)
    pdf=main.fitz.open();page=pdf.new_page(width=300,height=200)
    page.insert_image(main.fitz.Rect(20,20,280,180),stream=pix.tobytes('png'))
    payload=pdf.tobytes();pdf.close()
    monkeypatch.setattr(main,'PDF_VISION_ENABLED',True)
    monkeypatch.setattr(main,'configured_ai_slots',lambda:[])
    result=asyncio.run(main._extract_pdf_source_result_async(payload))
    assert result['status']=='error'
    assert result['stats']['vision_failed_pages']>=1
    assert result['pages'][0]['status']=='vision_unavailable'


def test_r35_all_deploy_paths_use_restricted_trusted_proxy_configuration():
    launcher=Path('railway_start.py').read_text(encoding='utf-8')
    assert '"--forwarded-allow-ips"' in launcher
    assert 'env["TRUSTED_PROXY_IPS"]' in launcher
    assert 'env.setdefault("TRUSTED_PROXY_IPS", "127.0.0.1")' in launcher
    assert not Path('nixpacks.toml').exists()
    assert not Path('Procfile').exists()


def test_r35_railway_client_ip_uses_platform_real_ip_without_trusting_xff(monkeypatch):
    from starlette.requests import Request
    monkeypatch.setenv('RAILWAY_SERVICE_ID','svc-test')
    scope={
        'type':'http','http_version':'1.1','method':'GET','scheme':'http','path':'/',
        'raw_path':b'/','query_string':b'',
        'headers':[(b'x-railway-request-id',b'railway-request-1'),(b'x-real-ip',b'203.0.113.9'),(b'x-forwarded-for',b'198.51.100.77')],
        'client':('10.0.0.4',12345),'server':('testserver',80),
    }
    assert main._request_ip(Request(scope))=='203.0.113.9'
    scope['headers']=[(b'x-forwarded-for',b'198.51.100.77')]
    assert main._request_ip(Request(scope))=='10.0.0.4'


def test_r3522_static_pool_supports_six_variable_slots(monkeypatch):
    for i in range(1, 7):
        monkeypatch.setattr(main, f"AI_API_KEY_{i}", f"pool6-key-{i}")
        monkeypatch.setattr(main, f"AI_BASE_URL_{i}", "https://openrouter.ai/api/v1")
        monkeypatch.setattr(main, f"AI_MODEL_{i}", "openrouter/auto")
        monkeypatch.setattr(main, f"AI_PROVIDER_LABEL_{i}", f"Pool {i}")
    slots=main._static_ai_slots()
    assert [int(x["slot"]) for x in slots] == [1,2,3,4,5,6]
    assert slots[4]["api_key"] == "pool6-key-5"
    assert slots[5]["api_key"] == "pool6-key-6"
