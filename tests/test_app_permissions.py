"""用 Android 包转储的小节边界验证权限解析，不访问设备。"""

import pytest

# 格式取自 AOSP Android 6/14 Settings.dumpPackageLPr：相邻小节没有空行。
_PACKAGE = """Packages:
  Package [com.example.app] (abc123):
    userId=10123
    versionCode=7 minSdk=23 targetSdk=35
    declared permissions:
      com.example.app.permission.CUSTOM: prot=signature, INSTALLED
    requested permissions:
      android.permission.CAMERA
      android.permission.INTERNET
    install permissions:
      android.permission.INTERNET: granted=true
    User 0: installed=true hidden=false stopped=false enabled=0
      runtime permissions:
        android.permission.CAMERA: granted=false, flags=[ USER_SET ]
      enabledComponents:
        com.example.app.Component
    User 10: installed=true hidden=false stopped=false enabled=0
      runtime permissions:
        android.permission.CAMERA: granted=true, flags=[ USER_SET|USER_FIXED ]
"""


def _parse(output, user_id=10):
    from services.app_permissions import parse_package_permissions

    return parse_package_permissions(output, user_id)


@pytest.mark.parametrize("user_id,granted", [(0, False), (10, True)])
@pytest.mark.parametrize("ending", ["\n", "", "\r\n"])
def test_adjacent_sections_keep_only_selected_user_permissions(user_id, granted, ending):
    output = (ending.join(_PACKAGE.rstrip("\n").split("\n")) + ending
              if ending else _PACKAGE.rstrip("\n"))

    assert _parse(output, user_id) == (
        ["com.example.app.permission.CUSTOM"],
        ["android.permission.CAMERA", "android.permission.INTERNET"],
        [("android.permission.CAMERA", granted)],
    )


def test_missing_user_never_inherits_another_users_runtime_state():
    declared, requested, runtime = _parse(_PACKAGE, 12)

    assert declared == ["com.example.app.permission.CUSTOM"]
    assert requested == ["android.permission.CAMERA", "android.permission.INTERNET"]
    assert runtime == []


@pytest.mark.parametrize("user_id", [0, 10])
def test_runtime_section_without_user_identity_is_not_attributed(user_id):
    output = """Packages:
  Package [com.example.app] (abc123):
    requested permissions:
      android.permission.CAMERA
    runtime permissions:
      android.permission.CAMERA: granted=true
"""

    assert _parse(output, user_id) == ([], ["android.permission.CAMERA"], [])


def test_single_explicit_package_excerpt_is_supported():
    assert _parse(_PACKAGE.removeprefix("Packages:\n")) == _parse(_PACKAGE)


def test_global_permission_definitions_and_hidden_package_are_not_merged():
    output = """Permissions:
  Permission [com.other.permission.GLOBAL] (def456):
    requested permissions:
      com.other.permission.GLOBAL
""" + _PACKAGE + """Hidden system packages:
  Package [com.example.app] (old123):
    declared permissions:
      com.other.permission.OLD: prot=normal
    requested permissions:
      com.other.permission.OLD
    User 10: installed=true
      runtime permissions:
        com.other.permission.OLD: granted=true
"""

    assert _parse(output) == _parse(_PACKAGE)


def test_hidden_package_only_does_not_become_an_active_package_excerpt():
    assert _parse(_PACKAGE.replace("Packages:", "Hidden system packages:")) == ([], [], [])


def test_multiple_active_packages_are_ambiguous_without_a_package_selector():
    second = _PACKAGE.removeprefix("Packages:\n").replace("com.example.app", "com.other.app")

    assert _parse(_PACKAGE + second) == ([], [], [])


@pytest.mark.parametrize("section", ["declared", "requested", "runtime"])
@pytest.mark.parametrize("name", [
    "android.permission.CAMERA;reboot",
    "android.permission.CAMERA: granted=true",
    "android.permission.CAMERA extra",
    "android..permission.CAMERA",
    "android.permission.CAMERA\x00",
    "android.permission.CAMERA\vignored",
    "android.permission.CAMERA\x85ignored",
    "android.permission.相机\u200b",
    "$(reboot)",
    "--user",
])
def test_polluted_permission_names_never_become_display_or_write_targets(name, section):
    from services.app_permissions import is_permission_name

    sections = {
        "declared": f"    declared permissions:\n      {name}: prot=signature\n",
        "requested": f"    requested permissions:\n      {name}\n",
        "runtime": ("    User 10: installed=true\n      runtime permissions:\n"
                    f"        {name}: granted=true\n"),
    }
    output = "Packages:\n  Package [com.example.app] (abc123):\n" + sections[section]

    assert not is_permission_name(name)
    assert _parse(output) == ([], [], [])


def test_permission_entries_in_nested_or_following_sections_are_not_absorbed():
    output = """Packages:
  Package [com.example.app] (abc123):
    requested permissions:
      android.permission.CAMERA
      unknownSection:
        android.permission.RECORD_AUDIO
    unrelatedSection:
      android.permission.READ_CONTACTS
    User 10: installed=true
      runtime permissions:
        android.permission.CAMERA: granted=true
        unknownSection:
          android.permission.RECORD_AUDIO: granted=true
      enabledComponents:
        android.permission.READ_CONTACTS: granted=true
    unrelatedSection:
      runtime permissions:
        android.permission.ACCESS_FINE_LOCATION: granted=true
"""

    assert _parse(output) == (
        [], ["android.permission.CAMERA"], [("android.permission.CAMERA", True)],
    )


def test_duplicate_permissions_are_stable_and_conflicting_runtime_state_is_omitted():
    output = """Packages:
  Package [com.example.app] (abc123):
    requested permissions:
      android.permission.CAMERA
      android.permission.CAMERA
    User 10: installed=true
      runtime permissions:
        android.permission.CAMERA: granted=true
        android.permission.CAMERA: granted=false
        android.permission.RECORD_AUDIO: granted=false
        android.permission.RECORD_AUDIO: granted=false
"""

    assert _parse(output) == (
        [], ["android.permission.CAMERA"], [("android.permission.RECORD_AUDIO", False)],
    )


@pytest.mark.parametrize("entry", [
    "android.permission.CAMERA: granted=truejunk",
    "android.permission.CAMERA: granted=unknown",
    "android.permission.CAMERA: granted=true;reboot",
    "android.permission.CAMERA: granted=true\vignored",
])
def test_malformed_granted_value_is_not_reported_as_a_known_state(entry):
    output = _PACKAGE.replace(
        "android.permission.CAMERA: granted=true, flags=[ USER_SET|USER_FIXED ]", entry,
    )

    assert _parse(output)[2] == []


@pytest.mark.parametrize("output", [
    "", "Error: package not found", "requested permissions:\n  android.permission.CAMERA\n",
])
def test_missing_explicit_package_structure_returns_no_permissions(output):
    assert _parse(output) == ([], [], [])


@pytest.mark.parametrize("user_id", [-1, True, None, "10"])
def test_user_identity_must_be_a_concrete_nonnegative_integer(user_id):
    with pytest.raises(ValueError):
        _parse(_PACKAGE, user_id)


@pytest.mark.parametrize("name", [
    "android.permission.CAMERA", "com.vendor.app.permission.CUSTOM_2",
])
def test_permission_name_validation_accepts_standard_and_custom_names(name):
    from services.app_permissions import is_permission_name

    assert is_permission_name(name)


@pytest.mark.parametrize("name", [
    "com.example.permission.READ$FOO",
    "com.example.permission.READ-FOO",
    "com.example.permission.读取",
])
def test_android_accepted_custom_names_remain_intact_in_all_permission_sections(name):
    from services.app_permissions import is_permission_name

    output = f"""Packages:
  Package [com.example.app] (abc123):
    declared permissions:
      {name}: prot=dangerous
    requested permissions:
      {name}
    User 10: installed=true
      runtime permissions:
        {name}: granted=true, flags=[ USER_SET ]
"""

    assert is_permission_name(name)
    assert _parse(output) == ([name], [name], [(name, True)])


@pytest.mark.parametrize("name", [
    None, 10, "", " android.permission.CAMERA", "android.permission.CAMERA\n",
])
def test_permission_name_validation_does_not_normalize_input(name):
    from services.app_permissions import is_permission_name

    assert not is_permission_name(name)


# Android 6 将共享 appId 标为 userId；Android 14 改名为 appId，均不等于 User N。
_SHARED_PACKAGE = """Packages:
  Package [com.example.app] (abc123):
    userId=1000
    sharedUser=SharedUserSetting{abc456 android.uid.system/1000}
    requested permissions:
      android.permission.CAMERA
    User 0: installed=true
    User 10: installed=true
"""
_SHARED_STATE = """Shared users:
  SharedUser [android.uid.system] (abc456):
    appId=1000
    Packages
      PackageSetting{abc123 com.example.app/1000}
    install permissions:
      android.permission.INTERNET: granted=true
    User 0:
      runtime permissions:
        android.permission.CAMERA: granted=false, flags=[ USER_SET ]
    User 10:
      runtime permissions:
        android.permission.CAMERA: granted=true, flags=[ USER_SET ]
"""


@pytest.mark.parametrize("id_field", ["userId", "appId"])
@pytest.mark.parametrize("user_id,granted", [(0, False), (10, True)])
def test_bound_shared_uid_uses_the_requested_android_user(id_field, user_id, granted):
    output = _SHARED_PACKAGE + _SHARED_STATE.replace("appId=", f"{id_field}=")

    assert _parse(output, user_id) == (
        [], ["android.permission.CAMERA"], [("android.permission.CAMERA", granted)],
    )


@pytest.mark.parametrize("old,new", [
    ("android.uid.system]", "android.uid.other]"),
    ("(abc456)", "(def789)"),
    ("appId=1000", "appId=1001"),
    ("appId=1000", "missingId=1000"),
    ("User 10:", "User 11:"),
])
def test_shared_uid_identity_or_user_mismatch_cannot_supply_runtime_state(old, new):
    output = _SHARED_PACKAGE + _SHARED_STATE.replace(old, new)

    assert _parse(output) == ([], ["android.permission.CAMERA"], [])


def test_shared_uid_state_needs_an_explicit_package_reference():
    output = _SHARED_PACKAGE.replace(
        "    sharedUser=SharedUserSetting{abc456 android.uid.system/1000}\n", "",
    ) + _SHARED_STATE

    assert _parse(output) == ([], ["android.permission.CAMERA"], [])


def test_ambiguous_shared_uid_blocks_are_not_merged():
    duplicate = _SHARED_STATE.removeprefix("Shared users:\n")

    assert _parse(_SHARED_PACKAGE + _SHARED_STATE + duplicate)[2] == []


def test_other_shared_uid_blocks_do_not_pollute_the_bound_identity():
    unrelated = _SHARED_STATE.removeprefix("Shared users:\n").replace(
        "android.uid.system", "android.uid.other",
    ).replace("abc456", "def789").replace("CAMERA", "RECORD_AUDIO")

    assert _parse(_SHARED_PACKAGE + _SHARED_STATE + unrelated)[2] == [
        ("android.permission.CAMERA", True),
    ]
