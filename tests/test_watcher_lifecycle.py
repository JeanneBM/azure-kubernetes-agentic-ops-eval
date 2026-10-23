"""Watch recovery and shutdown without Kubernetes or real waits."""
import threading
from unittest.mock import Mock

from agentic_ops import watcher


def test_bad_event_does_not_prevent_next_event(monkeypatch):
    stop = threading.Event()
    pod = object()
    def events(*args, **kwargs):
        yield {'type': 'DELETED', 'object': pod}
        yield {'type': 'ADDED', 'object': pod}
        yield {'type': 'MODIFIED', 'object': pod}
        stop.set()
    watch = Mock()
    watch.stream.side_effect = events
    monkeypatch.setattr(watcher.watch, 'Watch', lambda: watch)
    instance = watcher.PodWatcher(Mock(), Mock(), 'test-app', Mock())
    instance.process_pod = Mock(side_effect=[RuntimeError('bad pod'), True])
    instance.run(stop)
    assert instance.process_pod.call_count == 2
    assert watch.stream.call_args.args[1] == 'test-app'


def test_watch_disconnect_waits_before_reconnect(monkeypatch):
    stop = Mock()
    stop.is_set.side_effect = [False, True]
    watch = Mock()
    watch.stream.side_effect = RuntimeError('API unavailable')
    monkeypatch.setattr(watcher.watch, 'Watch', lambda: watch)
    watcher.PodWatcher(Mock(), Mock(), 'test-app', Mock()).run(stop)
    stop.wait.assert_called_once_with(5)


def test_stop_during_stream_does_not_process_event(monkeypatch):
    stop = threading.Event()
    def events(*args, **kwargs):
        stop.set()
        yield {'type': 'ADDED', 'object': object()}
    watch = Mock()
    watch.stream.side_effect = events
    monkeypatch.setattr(watcher.watch, 'Watch', lambda: watch)
    instance = watcher.PodWatcher(Mock(), Mock(), 'test-app', Mock())
    instance.process_pod = Mock()
    instance.run(stop)
    instance.process_pod.assert_not_called()
