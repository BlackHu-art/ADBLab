APP_NAME = "ADBLab"
APP_VERSION = "3.1.1"
APP_RELEASE_TAG = f"v{APP_VERSION}"


def app_major_minor_version() -> str:
    return APP_VERSION.rsplit(".", 1)[0]
