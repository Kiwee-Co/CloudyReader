import importlib.metadata

from cloudyreader.gui import names


def test_app_version_reads_the_installed_package_metadata():
    assert names.app_version() == importlib.metadata.version("cloudyreader")


def test_app_version_falls_back_to_dev_without_metadata(monkeypatch):
    def missing(_name):
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(names, "version", missing)

    assert names.app_version() == "dev"
