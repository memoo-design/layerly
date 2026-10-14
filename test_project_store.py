import threading
import pytest
from project_store import ProjectStore


def test_expiration_renewal_restart_and_unrelated_files(tmp_path):
    now = [1000]
    store = ProjectStore(tmp_path, retention=300, clock=lambda: now[0])
    first, token = store.create(b'image')
    second, other = store.create(b'other')
    unrelated = tmp_path / 'keep.txt'
    unrelated.write_text('user file')
    unknown = tmp_path / ('f' * 32)
    unknown.mkdir()
    (unknown / 'cleaned.png').write_bytes(b'not registered')
    now[0] += 200
    assert store.access(first, token) == b'image'
    now[0] += 101
    restarted = ProjectStore(tmp_path, retention=300, clock=lambda: now[0])
    assert restarted.cleanup() == 1
    assert restarted.path(first).exists()
    assert not restarted.path(second).exists()
    assert unrelated.read_text() == 'user file'
    assert (unknown / 'cleaned.png').exists()
    with pytest.raises(FileNotFoundError):
        restarted.access(second, other)
    now[0] += 301
    assert restarted.cleanup() == 1


def test_authorization_and_traversal(tmp_path):
    store = ProjectStore(tmp_path)
    project, token = store.create(b'image')
    for project_id, credential in [(project, ''), (project, 'wrong'), ('../secret', token)]:
        with pytest.raises(FileNotFoundError):
            store.access(project_id, credential)
    assert store.access(project, token, read=False) is None


def test_cleanup_keeps_unknown_contents(tmp_path):
    store = ProjectStore(tmp_path, clock=lambda: 1)
    project, _ = store.create(b'image')
    unknown = store.path(project).parent / 'user.txt'
    unknown.write_text('keep')
    store.clock = lambda: 100000
    assert store.cleanup() == 1
    assert unknown.read_text() == 'keep'


def test_cleanup_waits_for_active_operation(tmp_path):
    store = ProjectStore(tmp_path, clock=lambda: 1)
    project, _ = store.create(b'image')
    store.clock = lambda: 100000
    started, finished = threading.Event(), threading.Event()
    def sweep():
        started.set()
        store.cleanup()
        finished.set()
    with store.transaction():
        thread = threading.Thread(target=sweep)
        thread.start()
        assert started.wait(2)
        assert not finished.wait(.1)
        assert store.path(project).exists()
    thread.join(5)
    assert finished.is_set()


def test_private_route_and_heartbeat(tmp_path, monkeypatch):
    import app as backend
    now = [1]
    store = ProjectStore(tmp_path, retention=300, clock=lambda: now[0])
    monkeypatch.setattr(backend, 'project_store', store)
    project, token = store.create(b'png')
    client = backend.app.test_client()
    url = f'/api/projects/{project}/background?token={token}'
    now[0] = 200
    assert client.post(url).status_code == 200
    now[0] = 350
    assert store.cleanup() == 0
    assert client.get(url).data == b'png'
    assert client.get('/static/uploads/anything.png').status_code == 404
    assert client.get('/static/processed/anything.png').status_code == 404
    now[0] = 700
    assert client.post(url).status_code == 404
    assert client.get(url).status_code == 404


def test_request_log_redacts_token():
    import logging
    from app import RedactProjectTokens
    record = logging.LogRecord('werkzeug', logging.INFO, '', 0,
                               'GET %s', ('/api/projects/id/background?token=secret-value',), None)
    assert RedactProjectTokens().filter(record)
    assert 'secret-value' not in record.getMessage()
    assert '[redacted]' in record.getMessage()
