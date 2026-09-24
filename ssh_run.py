"""Helper to run commands on the remote AutoDL server via paramiko.

Usage:
    python ssh_run.py "command to run"
    python ssh_run.py --file local_script.sh   # upload & run a bash script

Connection details are read from env vars if present, else defaults below.
"""
import sys
import os
import paramiko

# Never hard-code credentials. Set these via environment variables:
#   OA_HOST, OA_PORT, OA_USER, OA_PASS   (or use an SSH key / config instead)
HOST = os.environ.get("OA_HOST", "")
PORT = int(os.environ.get("OA_PORT", "22"))
USER = os.environ.get("OA_USER", "root")
PASS = os.environ.get("OA_PASS", "")

if not HOST or not PASS:
    raise SystemExit(
        "Missing connection info. Set OA_HOST / OA_PORT / OA_USER / OA_PASS "
        "environment variables before running (credentials must not be "
        "committed to the repo)."
    )


def get_client():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=HOST,
        port=PORT,
        username=USER,
        password=PASS,
        timeout=30,
        banner_timeout=30,
        auth_timeout=30,
    )
    return client


def run(client, cmd, timeout=None):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout, get_pty=False)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    return code, out, err


def main():
    if len(sys.argv) < 2:
        print("usage: python ssh_run.py <command>")
        sys.exit(2)

    if sys.argv[1] == "--get":
        # download remote files to a local dir: --get <localdir> <remote1> ...
        localdir = sys.argv[2]
        os.makedirs(localdir, exist_ok=True)
        client = get_client()
        sftp = client.open_sftp()
        for remote in sys.argv[3:]:
            local = os.path.join(localdir, os.path.basename(remote))
            sftp.get(remote, local)
            print(f"get {remote} -> {local} ({os.path.getsize(local)} bytes)")
        sftp.close()
        client.close()
        return

    if sys.argv[1] == "--put":
        # upload one or more local files to /root/ (normalize LF), no exec
        client = get_client()
        sftp = client.open_sftp()
        for local in sys.argv[2:]:
            with open(local, "rb") as f:
                data = f.read().replace(b"\r\n", b"\n")
            remote = "/root/" + os.path.basename(local)
            with sftp.open(remote, "wb") as rf:
                rf.write(data)
            print(f"put {local} -> {remote}")
        sftp.close()
        client.close()
        return

    if sys.argv[1] == "--file":
        local = sys.argv[2]
        remote = "/root/" + os.path.basename(local)
        # normalize CRLF -> LF so bash on Linux is happy
        with open(local, "rb") as f:
            data = f.read().replace(b"\r\n", b"\n")
        client = get_client()
        sftp = client.open_sftp()
        with sftp.open(remote, "wb") as rf:
            rf.write(data)
        sftp.close()
        code, out, err = run(client, f"bash {remote}")
        print(out)
        if err:
            print("STDERR:\n" + err)
        print(f"[exit {code}]")
        client.close()
        return

    cmd = sys.argv[1]
    client = get_client()
    code, out, err = run(client, cmd)
    print(out)
    if err:
        print("STDERR:\n" + err)
    print(f"[exit {code}]")
    client.close()


if __name__ == "__main__":
    main()
