import json
import os
from pathlib import Path

import pytest
import test_release as base

main = base.main

def setup_module():
    main.init_storage()
    main.ensure_schema()
    main.seed_admin()


def test_r351_thinking_component_is_single_canonical_rule_and_right_aligned():
    import ui_templates
    assert ui_templates.MAIN_HTML.count('BARSAN R35.2 canonical thinking loader') == 1
    assert ui_templates.WIDGET_HTML.count('BARSAN R35.2 canonical thinking loader') == 1
    for html in (ui_templates.MAIN_HTML, ui_templates.WIDGET_HTML):
        assert 'margin:8px 0 10px auto!important' in html
        assert 'width:196px!important' in html
        assert 'width:164px!important' in html
        assert '/thinking-loader.mp4?v=R35_2' in html


def test_r351_cache_rejects_document_that_becomes_non_ready_without_version_bump():
    q='تست محافظ کش منبع مسدود R351'
    doc_id='doc-cache-eligibility-r351'
    base.insert_document(doc_id,'cache-eligibility-r351.txt',['پاسخ قطعی تست محافظ کش.'])
    sources=[{'source_type':'document','document_id':doc_id,'file_name':'cache-eligibility-r351.txt','score':0.9,'excerpt':'پاسخ قطعی'}]
    main.store_cached_answer(q,False,None,True,'پاسخ قطعی تست محافظ کش.',sources,'test-model',cache_tier='approved')
    assert main.find_exact_cached_answer(q,False,None,True) is not None
    with main.get_db() as db:
        db.execute("UPDATE documents SET status='partial' WHERE id=?",(doc_id,))
    assert main.find_exact_cached_answer(q,False,None,True) is None
    assert main.find_cached_answer(q,False,None,True) is None


def test_r351_failed_staging_reindex_keeps_previous_ready_index(monkeypatch, tmp_path):
    doc_id='doc-staging-r351';job_id='job-staging-r351'
    stored=tmp_path/'staging.txt';stored.write_text('old ready content',encoding='utf-8')
    base.insert_document(doc_id,'staging.txt',['old ready content'])
    with main.get_db() as db:
        db.execute('UPDATE documents SET stored_path=?,status=\'ready\',chunk_count=1,reindex_status=\'queued\' WHERE id=?',(str(stored),doc_id))
        db.execute("INSERT OR REPLACE INTO document_jobs(id,document_id,status,progress,phase,created_by,created_at,updated_at,job_type,payload_json,attempts,max_attempts,next_run_at,priority) VALUES(?,?,'processing',20,'test',NULL,?,?, 'reindex','{}',1,1,?,60)",(job_id,doc_id,main.now_iso(),main.now_iso(),main.now_iso()))
    monkeypatch.setattr(main,'extract_document_result_from_path',lambda *a,**k:{'text':'partial new','kind':'text','pages':[],'warnings':['forced staging fail'],'status':'partial','stats':{'ingestion_quality_pct':50,'vision_failed_pages':1}})
    main._process_document_job(job_id,doc_id)
    with main.get_db() as db:
        doc=db.execute('SELECT status,chunk_count,reindex_status,reindex_error FROM documents WHERE id=?',(doc_id,)).fetchone()
        job=db.execute('SELECT status FROM document_jobs WHERE id=?',(job_id,)).fetchone()
    assert doc['status']=='ready'
    assert int(doc['chunk_count'])==1
    assert doc['reindex_status']=='error'
    assert doc['reindex_error']
    assert job['status']=='error'


def test_r351_document_queue_prioritizes_ingest_over_background_reindex():
    with main.get_db() as db:
        rows=db.execute("SELECT priority,job_type FROM document_jobs WHERE id IN ('job-priority-upload-r351','job-priority-bg-r351')").fetchall()
        for ident in ('doc-priority-upload-r351','doc-priority-bg-r351'):
            db.execute("INSERT OR REPLACE INTO documents(id,filename,stored_path,mime_type,visibility,status,character_count,chunk_count,version,created_at) VALUES(?,?,?,?,?,'processing',0,0,1,?)",(ident,ident+'.txt',str(base.TEST_ROOT / f'{ident}.txt'),'text/plain','public',main.now_iso()))
        db.execute("INSERT OR REPLACE INTO document_jobs(id,document_id,status,progress,phase,created_at,updated_at,job_type,attempts,max_attempts,next_run_at,priority) VALUES('job-priority-bg-r351','doc-priority-bg-r351','queued',5,'مهاجرت خودکار',?,?, 'reindex',0,3,?,20)",(main.now_iso(),main.now_iso(),main.now_iso()))
        db.execute("INSERT OR REPLACE INTO document_jobs(id,document_id,status,progress,phase,created_at,updated_at,job_type,attempts,max_attempts,next_run_at,priority) VALUES('job-priority-upload-r351','doc-priority-upload-r351','queued',5,'فایل دریافت شد',?,?, 'ingest',0,3,?,100)",(main.now_iso(),main.now_iso(),main.now_iso()))
    claimed=main._claim_next_document_job('priority-test-worker')
    assert claimed and claimed['id']=='job-priority-upload-r351'
    with main.get_db() as db:
        db.execute("DELETE FROM document_jobs WHERE id IN ('job-priority-upload-r351','job-priority-bg-r351')")
        db.execute("DELETE FROM documents WHERE id IN ('doc-priority-upload-r351','doc-priority-bg-r351')")


def test_r351_confidence_calibration_has_safe_active_default(monkeypatch):
    main._CONFIDENCE_CALIBRATION_CACHE=(0.0,None,{})
    with main.get_db() as db:
        db.execute('DELETE FROM golden_runs')
    threshold,meta=main.calibrated_confidence_threshold(0.56)
    assert threshold >= 0.56
    assert meta['active'] is True
    assert meta['mode']=='safe_default'


def test_r351_source_health_explicitly_reports_vision_readiness():
    token=base.owner_token()
    from fastapi.testclient import TestClient
    with TestClient(main.app) as client:
        r=client.get('/api/v1/admin/sources/health',headers={'Authorization':f'Bearer {token}'})
    assert r.status_code==200,r.text
    vision=r.json()['vision']
    assert {'configured','configured_slots','sources_needing_vision','ready'} <= set(vision)


def test_r351_readyz_does_not_expose_exception_text(monkeypatch):
    class BadDB:
        def __enter__(self):
            raise RuntimeError('/secret/internal/path/barsan.db exploded')
        def __exit__(self,*args):
            return False
    monkeypatch.setattr(main,'get_db',lambda:BadDB())
    response=main.readyz()
    body=json.loads(response.body)
    assert response.status_code==503
    assert body['error']=='database_unavailable'
    assert '/secret/' not in response.body.decode()


def test_r351_origin_guard_helper_rejects_cross_site_browser_mutation():
    from ops_runtime import same_origin_allowed
    allowed={'http://testserver','https://barsan.example'}
    assert same_origin_allowed('http://testserver',None,allowed) is True
    assert same_origin_allowed(None,'https://barsan.example/panel',allowed) is True
    assert same_origin_allowed('https://evil.example',None,allowed) is False
    assert same_origin_allowed(None,None,allowed) is False


def test_r351_security_headers_include_csp_and_request_id():
    from fastapi.testclient import TestClient
    with TestClient(main.app) as client:
        r=client.get('/healthz')
    assert r.status_code==200
    assert r.headers.get('x-request-id')
    csp=r.headers.get('content-security-policy','')
    assert "default-src 'self'" in csp
    assert "object-src 'none'" in csp
    assert "frame-ancestors 'self'" in csp


def test_r351_single_replica_lock_blocks_second_holder(tmp_path):
    if os.name != 'posix':
        pytest.skip('fcntl replica locking is only available on Railway/Linux')
    from ops_runtime import acquire_sqlite_replica_lock, release_sqlite_replica_lock, ReplicaLockError
    first=acquire_sqlite_replica_lock(tmp_path,enabled=True)
    try:
        try:
            acquire_sqlite_replica_lock(tmp_path,enabled=True)
        except ReplicaLockError:
            blocked=True
        else:
            blocked=False
        assert blocked is True
    finally:
        release_sqlite_replica_lock(first)


def test_r3523_railway_predeploy_is_explicitly_disabled():
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parent
    assert not (root / "railway.toml").exists()
    cfg = json.loads((root / "railway.json").read_text(encoding="utf-8"))
    assert cfg["build"]["builder"] == "DOCKERFILE"
    assert cfg["deploy"]["preDeployCommand"] is None
    assert cfg["deploy"]["healthcheckPath"] == "/healthz"
