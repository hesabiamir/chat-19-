import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import test_release as base

main=base.main


def setup_module():
    main.init_storage();main.ensure_schema();main.seed_admin()


def test_r352_public_base_explicit_config_wins_over_railway_domain():
    assert main.resolve_public_base_url('https://chat.example.com','temporary.up.railway.app')=='https://chat.example.com'
    assert main.resolve_public_base_url('','temporary.up.railway.app')=='https://temporary.up.railway.app'


def test_r352_integration_keys_support_json_and_legacy_formats(monkeypatch):
    monkeypatch.setattr(main,'INTEGRATION_API_KEYS_RAW','{"site":"abcdefghijklmnopqrstuvwx123456"}')
    assert main.parse_integration_keys()=={'site':'abcdefghijklmnopqrstuvwx123456'}
    monkeypatch.setattr(main,'INTEGRATION_API_KEYS_RAW','site:abcdefghijklmnopqrstuvwx123456,ops:zyxwvutsrqponmlkjihgfedcba987654')
    keys=main.parse_integration_keys()
    assert keys['site'].startswith('abcd') and keys['ops'].startswith('zyxw')


def test_r352_widget_csp_allows_only_configured_embed_origins(monkeypatch):
    monkeypatch.setattr(main,'WIDGET_ALLOWED_ORIGINS',['https://portal.example','https://ops.example'])
    widget=main._content_security_policy_for_path('/widget')
    admin=main._content_security_policy_for_path('/')
    assert "frame-ancestors 'self' https://portal.example https://ops.example" in widget
    assert "frame-ancestors 'self';" in admin
    assert 'portal.example' not in admin


def test_r352_railway_healthcheck_is_independent_of_database_readiness():
    import json
    railway=json.loads(Path(main.__file__).with_name('railway.json').read_text(encoding='utf-8'))
    assert railway['deploy']['preDeployCommand'] is None
    assert railway['deploy']['healthcheckPath']=='/healthz'


def test_r352_admin_password_sync_is_safe_by_default():
    assert main.SYNC_MASTER_ADMIN_CREDENTIALS is False


def test_r352_backup_limit_has_headroom_for_large_uploads():
    assert main.BACKUP_MAX_MB >= max(2048,main.MAX_UPLOAD_MB*2)


def test_r352_restore_sets_maintenance_gate_and_clears_it(monkeypatch):
    observed={}
    def fake_restore(payload,actor_id):
        observed['set']=main._RESTORE_IN_PROGRESS.is_set()
        return {'ok':True,'actor_id':actor_id,'uploads_restored':0}
    monkeypatch.setattr(main,'_restore_backup_bytes_unlocked',fake_restore)
    result=main.restore_backup_bytes(b'fake',123)
    assert result['ok'] is True
    assert observed['set'] is True
    assert main._RESTORE_IN_PROGRESS.is_set() is False


def test_r352_api_requests_are_blocked_during_restore():
    main._RESTORE_IN_PROGRESS.set()
    try:
        with TestClient(main.app) as client:
            response=client.get('/api/v1/admin/sources/health')
            ready=client.get('/readyz')
        assert response.status_code==503
        assert response.headers.get('retry-after')=='5'
        assert ready.status_code==503
        assert ready.json()['error']=='restore_in_progress'
    finally:
        main._RESTORE_IN_PROGRESS.clear()


def test_r352_document_worker_does_not_claim_during_restore(monkeypatch):
    calls={'claim':0}
    def claim(_):
        calls['claim']+=1
        return None
    monkeypatch.setattr(main,'_claim_next_document_job',claim)
    main._RESTORE_IN_PROGRESS.set()
    try:
        assert main._run_one_document_job_guarded('test-worker') is False
        assert calls['claim']==0
    finally:
        main._RESTORE_IN_PROGRESS.clear()


def test_r352_cors_accepts_both_integration_header_contracts():
    src=Path(main.__file__).read_text(encoding='utf-8')
    assert "'X-API-Key'" in src and "'X-Integration-Key'" in src
    assert "alias='X-API-Key'" in src and "alias='X-Integration-Key'" in src


def test_r3523_cargo_context_uses_defined_retrieval_and_formatter_contract():
    src=Path(main.__file__).read_text(encoding='utf-8')
    block=src[src.index('async def _cargo_context_note'):src.index("@app.post('/api/v1/cargo/check')")]
    assert 'authoritative_training' not in block
    assert 'format_answer_for_mode(raw,False,question)' not in block
    assert 'retrieve_priority_stage_async' in block
