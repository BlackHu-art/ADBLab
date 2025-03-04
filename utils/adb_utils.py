import subprocess

def execute_adb_command(command):
    """
    执行 adb 命令并返回输出字符串
    :param command: 完整的 adb 命令字符串
    :return: 命令输出
    """
    try:
        output = subprocess.check_output(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace")
        return output.strip()
    except subprocess.CalledProcessError as e:
        return f"Error: {e.output.strip()}"
