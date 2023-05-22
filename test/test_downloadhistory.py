from pijuv2.backend.downloadhistory import DownloadHistory


def test_history_starts_empty():
    history = DownloadHistory()
    assert len(history.entries) == 0


def test_history_can_add():
    history = DownloadHistory()
    history.add('http://some.url/')
    assert len(history.entries) == 1


def test_history_new_entry_is_inserted_at_front():
    history = DownloadHistory()
    history.add('url1')
    history.add('url2')
    assert history.entries[0] == 'url2'
    assert history.entries[1] == 'url1'


def test_history_max_length_enforced():
    history = DownloadHistory(max_length=3)
    history.add('url1')
    history.add('url2')
    history.add('url3')
    history.add('url4')
    assert history.entries == ['url4', 'url3', 'url2']


def test_history_repeat_add_moves_to_front():
    history = DownloadHistory()
    history.add('url1')
    history.add('url2')
    history.add('url3')
    assert history.entries == ['url3', 'url2', 'url1']
    history.add('url1')
    assert history.entries == ['url1', 'url3', 'url2']
