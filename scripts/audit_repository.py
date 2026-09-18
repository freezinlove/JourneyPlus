"""Read-only pre-upload checks. Reports paths/categories, never secret values.

Checks tracked and non-ignored new files in the working tree. --history additionally
scans every reachable Git blob. This is a heuristic check, not a security guarantee.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "private-key": rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    "github-token": rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})",
    "api-key": rb"\bsk-[A-Za-z0-9_-]{24,}",
    "google-token": rb"\b(?:GOCSPX-[A-Za-z0-9_-]{20,}|ya29\.[A-Za-z0-9_-]{25,})",
}


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true")
    args = parser.parse_args()
    known = []
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" not in line or line.lstrip().startswith("#"):
                continue
            key, value = line.split("=", 1)
            value = value.strip().strip("\"'")
            if (re.search("API_KEY|PASSWORD|SECRET|TOKEN", key)
                    and not re.search("FILE|PATH", key) and len(value) >= 12):
                known.append(value.encode())

    findings = []

    def inspect(path, data, scope):
        categories = [name for name, pattern in PATTERNS.items() if re.search(pattern, data)]
        if any(value in data for value in known):
            categories.append("matches-local-secret")
        if categories:
            findings.append({"scope": scope, "path": path, "categories": categories})

    paths = [p.decode() for p in git("ls-files", "-z").split(b"\0") if p]
    new_paths = [p.decode() for p in git("ls-files", "--others", "--exclude-standard", "-z").split(b"\0") if p]
    for path in paths + new_paths:
        file = ROOT / path
        if file.is_file():
            inspect(path, file.read_bytes(), "working-tree")
    ignored = git("ls-files", "-ci", "--exclude-standard", "-z").split(b"\0")
    for path in ignored:
        if path:
            findings.append({"scope": "index", "path": path.decode(), "categories": ["tracked-but-ignored"]})

    blob_count = 0
    if args.history:
        entries = git("rev-list", "--objects", "--all").splitlines()
        with subprocess.Popen(["git", "cat-file", "--batch"], cwd=ROOT,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE) as proc:
            for entry in entries:
                oid, _, path = entry.partition(b" ")
                proc.stdin.write(oid + b"\n")
                proc.stdin.flush()
                header = proc.stdout.readline().split()
                data = proc.stdout.read(int(header[2]))
                proc.stdout.read(1)
                if header[1] == b"blob":
                    blob_count += 1
                    inspect(path.decode(errors="replace"), data, "history:" + oid.decode()[:12])
            proc.stdin.close()
            proc.wait()
    print(json.dumps({"tracked_paths": len(paths), "new_paths": len(new_paths), "historical_blobs": blob_count,
                      "findings": findings}, ensure_ascii=False, indent=2))
    return bool(findings)


if __name__ == "__main__":
    raise SystemExit(main())
