"""集中定义应用名称、版本和发布标签。"""

APP_NAME = "ADBLab"
APP_VERSION = "3.2.1"
APP_RELEASE_TAG = f"v{APP_VERSION}"


def app_major_minor_version() -> str:
    """返回不含补丁号的主次版本。"""
    return APP_VERSION.rsplit(".", 1)[0]
