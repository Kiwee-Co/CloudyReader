"""User-visible names. One place, so the title, About box, menus, and QSettings agree."""

from importlib.metadata import PackageNotFoundError, version

APP_NAME = "Cloudy Reader"  # shown to the user; the space is on purpose
ORG_NAME = "CloudyReader"  # QSettings key prefix: no space


def app_version() -> str:
    """The installed package version, or "dev" when no metadata is there (a bare checkout)."""
    try:
        return version("cloudyreader")
    except PackageNotFoundError:
        return "dev"
