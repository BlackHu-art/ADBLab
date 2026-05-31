from models import file_explorer_service as explorer_service


def test_parse_ls_output_sorts_folders_first_and_tracks_symlinks():
    output = """
total 12
drwxr-xr-x 2 shell shell 4096 May 30 Camera
-rw-r--r-- 1 shell shell 1536 May 30 readme.txt
lrwxrwxrwx 1 shell shell 11 May 30 dcim-link -> /sdcard/DCIM
-rw-r--r-- 1 shell shell 2048 May 30 archive.tar.gz
ls: /sdcard/secret: Permission denied
"""

    rows, links = explorer_service.parse_ls_output(output)

    assert [row.name for row in rows] == ["Camera", "dcim-link", "archive.tar.gz", "readme.txt"]
    assert [row.file_type for row in rows] == ["Folder", "Folder", "GZ", "TXT"]
    assert rows[2].size_text == "2.0 KB"
    assert rows[3].size == 1536
    assert links == {"dcim-link": "/sdcard/DCIM"}


def test_safe_name_blocks_path_segments_and_shell_metacharacters():
    assert explorer_service.safe_name("screen_record.mp4") is True
    assert explorer_service.safe_name("../data") is False
    assert explorer_service.safe_name("..") is False
    assert explorer_service.safe_name("bad;rm") is False
    assert explorer_service.safe_name("") is False


def test_chmod_mode_helpers_normalize_and_build_mode():
    states = {
        ("owner", "r"): True,
        ("owner", "w"): True,
        ("owner", "x"): True,
        ("group", "r"): True,
        ("group", "w"): False,
        ("group", "x"): True,
        ("other", "r"): True,
        ("other", "w"): False,
        ("other", "x"): False,
    }

    assert explorer_service.mode_from_permissions(states) == "754"
    assert explorer_service.normalize_mode("0755\n", is_dir=False) == "755"
    assert explorer_service.normalize_mode("bad", is_dir=True) == "755"
    assert explorer_service.normalize_mode("bad", is_dir=False) == "644"


def test_file_explorer_command_builders_keep_current_shell_contract():
    assert explorer_service.root_command("ls -la '/sdcard/My Dir'", True) == (
        'su -c \'ls -la \'"\'"\'/sdcard/My Dir\'"\'"\'\''
    )
    assert explorer_service.ls_command("/sdcard/My Dir/$tmp") == (
        "ls -la '/sdcard/My Dir/$tmp' 2>&1"
    )
    assert explorer_service.copy_for_root_pull_command("/a b", "/tmp/a'b") == (
        "dd if='/a b' of='/tmp/a'\"'\"'b' && chmod 644 '/tmp/a'\"'\"'b'"
    )
    assert explorer_service.script_command("/tmp/a.sh", True) == (
        "chmod +x '/tmp/a.sh' && sh '/tmp/a.sh'"
    )


def test_parse_ls_output_only_splits_symlink_targets_for_symlink_entries():
    output = "-rw-r--r-- 1 shell shell 12 May 30 report -> draft.txt\n"

    rows, links = explorer_service.parse_ls_output(output)

    assert rows[0].name == "report -> draft.txt"
    assert rows[0].file_type == "TXT"
    assert links == {}
