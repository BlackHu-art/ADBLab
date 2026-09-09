"""集中定义应用名称、版本和发布标签。"""

APP_NAME = "ADBLab"
APP_VERSION = "3.2.11"
APP_RELEASE_TAG = f"v{APP_VERSION}"
APP_REPOSITORY = "BlackHu-art/ADBLab"
APP_PROJECT_URL = f"https://github.com/{APP_REPOSITORY}"
APP_RELEASES_URL = f"{APP_PROJECT_URL}/releases"
APP_UPDATE_API_URL = f"https://api.github.com/repos/{APP_REPOSITORY}/releases/latest"


def app_major_minor_version() -> str:
    """返回不含补丁号的主次版本。"""
    return APP_VERSION.rsplit(".", 1)[0]
