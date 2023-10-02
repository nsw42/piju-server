from pathlib import Path

from pijuv2.backend.downloadinfo import DownloadInfoDatabaseSingleton


def test_singleton_is_unique():
    inst1 = DownloadInfoDatabaseSingleton()
    inst2 = DownloadInfoDatabaseSingleton()
    assert inst1 is inst2


def test_get_values_are_distinct():
    db = DownloadInfoDatabaseSingleton()
    val1 = db.get_id_for_filepath('path1')
    val2 = db.get_id_for_filepath('path2')
    assert val1 != val2


def test_get_path_and_str_are_equivalent():
    db = DownloadInfoDatabaseSingleton()
    val1 = db.get_id_for_filepath(Path('/over/there'))
    val2 = db.get_id_for_filepath('/over/there')
    assert val1 == val2

    val3 = db.get_id_for_filepath('/somewhere/else')
    assert val1 != val3
