"""Start local development processes with bounded, inspectable log files."""
import argparse
import subprocess
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("task", choices=["server", "docker-build", "evaluation", "postfix-evaluation", "newest-evaluation", "fresh-evaluation"])
args = parser.parse_args()
data = Path("data")
data.mkdir(exist_ok=True)
commands = {
    "server": [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
    "docker-build": ["docker", "build", "--progress=plain", "-t", "jobsource-agent:local", "."],
    "evaluation": [sys.executable, "-u", "-m", "evaluation.run"],
    "postfix-evaluation": [sys.executable, "-u", "-m", "evaluation.run", "--kind", "post-fix", "--output-dir", "evaluation/postfix-v2"],
    "newest-evaluation": [sys.executable, "-u", "-m", "evaluation.run", "--kind", "post-fix", "--output-dir", "evaluation/newest-v3", "--run-protocol", "evaluation/NEWEST_PROTOCOL.md"],
    "fresh-evaluation": [sys.executable, "-u", "-m", "evaluation.run", "--kind", "fresh", "--output-dir", "evaluation/fresh-current", "--sample", "evaluation/fresh-current/sample.json", "--selection-protocol", "evaluation/fresh-current/PROTOCOL.md", "--run-protocol", "evaluation/fresh-current/PROTOCOL.md", "--concurrency", "3"],
}
command = commands[args.task]
log_path = data / f"{args.task}.log"
with log_path.open("w") as log:
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
(data / f"{args.task}.pid").write_text(str(process.pid))
print(f"Started {args.task}: pid={process.pid}, log={log_path}")
