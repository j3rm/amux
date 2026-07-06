#!/usr/bin/env python3
"""Perf monitor — samples host + amux/claude process state every N seconds and
appends one JSONL record per sample to ~/.amux/logs/perf.jsonl.

Cheap by design: shells out to `ps`, `free`, `ss`, reads /proc/loadavg,
/proc/meminfo, /proc/stat. No third-party deps. Runs in a loop; safe to
`nohup ... &` or drop into a systemd unit.

Each record:
{
  "ts": "2026-07-06T21:50:00Z",
  "uptime_s": 12345,
  "load": [1m, 5m, 15m],
  "mem": {"total_kb": ..., "used_kb": ..., "free_kb": ..., "cached_kb": ...,
          "swap_used_kb": ..., "available_kb": ...},
  "cpu": {"pct_busy": 12.3, "cores": 8},
  "counts": {"claude": 40, "tmux_server": 1, "tmux_sessions": 38,
             "amux_server": 1, "python": 55, "node": 12, "conns_8822": 47},
  "amux": {"pid": 1292, "rss_kb": 512000, "cpu_pct": 3.1, "start": "21:41"},
  "top_rss": [{"pid": 1155, "cmd": "claude ...", "rss_kb": 342996, "pct": 0.5}, ...15]
}

Also writes a rolling 24h `perf-summary.txt` next to it every 5 minutes with the
last hour's min/mean/max for mem_used, swap_used, load1, claude_count.
"""

import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

INTERVAL_S = int(os.environ.get("PERF_INTERVAL", "30"))
LOG_DIR = Path(os.environ.get("PERF_LOG_DIR", os.path.expanduser("~/.amux/logs")))
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "perf.jsonl"
SUMMARY_FILE = LOG_DIR / "perf-summary.txt"
TOP_N = 15
SUMMARY_EVERY_S = 300  # 5 min


def sh(cmd, timeout=5):
    try:
        return subprocess.run(
            cmd, shell=isinstance(cmd, str), capture_output=True,
            text=True, timeout=timeout,
        ).stdout
    except Exception as e:
        return ""


def read_meminfo():
    d = {}
    try:
        for line in open("/proc/meminfo"):
            k, _, rest = line.partition(":")
            v = rest.strip().split()
            if v:
                d[k] = int(v[0])  # kB
    except Exception:
        pass
    return d


def read_loadavg():
    try:
        parts = open("/proc/loadavg").read().split()
        return [float(x) for x in parts[:3]]
    except Exception:
        return [0.0, 0.0, 0.0]


_last_cpu = {"total": 0, "idle": 0}


def read_cpu_pct():
    """Compute % busy since last call from /proc/stat."""
    try:
        first_line = open("/proc/stat").readline()
        parts = first_line.split()[1:]
        vals = list(map(int, parts))
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)  # idle + iowait
        total = sum(vals)
        dt = total - _last_cpu["total"]
        di = idle - _last_cpu["idle"]
        _last_cpu["total"] = total
        _last_cpu["idle"] = idle
        if dt <= 0:
            return None
        return round(100.0 * (dt - di) / dt, 2)
    except Exception:
        return None


def read_uptime_s():
    try:
        return int(float(open("/proc/uptime").read().split()[0]))
    except Exception:
        return 0


def ps_snapshot():
    """Return list of (pid, rss_kb, pct_mem, pct_cpu, cmd_trimmed) sorted by
    RSS desc. Uses `ps -eo` for portability. Trims cmd to ~120 chars."""
    out = sh(["ps", "-eo", "pid,rss,pmem,pcpu,comm,args", "--no-headers"])
    procs = []
    for line in out.splitlines():
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        try:
            pid = int(parts[0]); rss = int(parts[1])
            pmem = float(parts[2]); pcpu = float(parts[3])
        except ValueError:
            continue
        comm = parts[4]
        args = parts[5][:200]
        procs.append((pid, rss, pmem, pcpu, comm, args))
    procs.sort(key=lambda r: r[1], reverse=True)
    return procs


def count_conns_8822():
    out = sh("ss -tn state established '( sport = :8822 or dport = :8822 )' 2>/dev/null | wc -l")
    try:
        return max(0, int(out.strip()) - 0)
    except Exception:
        return -1


def count_tmux_sessions():
    out = sh(["tmux", "list-sessions", "-F", "#{session_name}"])
    return len([x for x in out.splitlines() if x.strip()])


def find_amux(procs):
    """procs = list from ps_snapshot(). Return dict for amux-server.py or None."""
    for pid, rss, pmem, pcpu, comm, args in procs:
        if "amux-server.py" in args and "python" in comm:
            return {"pid": pid, "rss_kb": rss, "cpu_pct": pcpu}
    return None


def collect(sample_idx):
    procs = ps_snapshot()
    counts = {
        "claude": 0, "tmux_server": 0, "python": 0, "node": 0,
        "amux_server": 0,
    }
    for pid, rss, pmem, pcpu, comm, args in procs:
        c = comm.lower()
        if c == "claude" or args.startswith("claude "):
            counts["claude"] += 1
        if c == "tmux" or c.startswith("tmux:"):
            counts["tmux_server"] += 1
        if "python" in c:
            counts["python"] += 1
        if c == "node":
            counts["node"] += 1
        if "amux-server.py" in args:
            counts["amux_server"] += 1
    counts["tmux_sessions"] = count_tmux_sessions()
    counts["conns_8822"] = count_conns_8822()

    mi = read_meminfo()
    mem = {
        "total_kb": mi.get("MemTotal", 0),
        "free_kb": mi.get("MemFree", 0),
        "available_kb": mi.get("MemAvailable", 0),
        "cached_kb": mi.get("Cached", 0),
        "buffers_kb": mi.get("Buffers", 0),
        "swap_total_kb": mi.get("SwapTotal", 0),
        "swap_free_kb": mi.get("SwapFree", 0),
    }
    mem["used_kb"] = mem["total_kb"] - mem["available_kb"]
    mem["swap_used_kb"] = mem["swap_total_kb"] - mem["swap_free_kb"]

    cpu_pct = read_cpu_pct()
    if sample_idx == 0:
        cpu_pct = None  # first sample has no delta

    rec = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "uptime_s": read_uptime_s(),
        "load": read_loadavg(),
        "cores": os.cpu_count(),
        "cpu_pct_busy": cpu_pct,
        "mem": mem,
        "counts": counts,
        "amux": find_amux(procs),
        "top_rss": [
            {"pid": p[0], "rss_kb": p[1], "pct_mem": p[2], "pct_cpu": p[3],
             "cmd": p[5][:160]}
            for p in procs[:TOP_N]
        ],
    }
    return rec


def write_summary(recent):
    """recent: deque of records covering the last hour (approx)."""
    if not recent:
        return
    def col(key_path):
        vals = []
        for r in recent:
            v = r
            try:
                for k in key_path:
                    v = v[k]
                if v is None:
                    continue
                vals.append(float(v))
            except (KeyError, TypeError):
                continue
        return vals
    def mmm(vals):
        if not vals:
            return "  -  "
        return f"min={min(vals):.1f} avg={sum(vals)/len(vals):.1f} max={max(vals):.1f}"
    lines = [
        f"# perf-summary (rolling ~1h, updated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%SZ')})",
        f"samples: {len(recent)}",
        f"load1        {mmm(col(['load', 0]) if recent else [])}"
            .replace('col', ''),
    ]
    # rebuild cleanly (col trick above was ugly)
    lines = [
        f"# perf-summary (rolling ~1h, updated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%SZ')})",
        f"samples in window: {len(recent)}",
        f"load1               {mmm([r['load'][0] for r in recent])}",
        f"cpu_pct_busy        {mmm([r['cpu_pct_busy'] for r in recent if r['cpu_pct_busy'] is not None])}",
        f"mem_used_gb         {mmm([r['mem']['used_kb']/1024/1024 for r in recent])}",
        f"mem_available_gb    {mmm([r['mem']['available_kb']/1024/1024 for r in recent])}",
        f"swap_used_gb        {mmm([r['mem']['swap_used_kb']/1024/1024 for r in recent])}",
        f"claude_procs        {mmm([r['counts']['claude'] for r in recent])}",
        f"conns_8822          {mmm([r['counts']['conns_8822'] for r in recent if r['counts']['conns_8822'] >= 0])}",
    ]
    amux_rss = [r['amux']['rss_kb']/1024 for r in recent if r.get('amux')]
    if amux_rss:
        lines.append(f"amux_server_mb      {mmm(amux_rss)}")
    SUMMARY_FILE.write_text("\n".join(lines) + "\n")


def main():
    stop = {"flag": False}
    def _sig(*_):
        stop["flag"] = True
    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)

    read_cpu_pct()  # prime
    window_len = max(1, 3600 // INTERVAL_S)
    recent = deque(maxlen=window_len)
    last_summary = 0
    idx = 0
    with open(LOG_FILE, "a", buffering=1) as f:
        while not stop["flag"]:
            try:
                rec = collect(idx)
                f.write(json.dumps(rec, separators=(",", ":")) + "\n")
                recent.append(rec)
                now = time.time()
                if now - last_summary >= SUMMARY_EVERY_S:
                    write_summary(recent)
                    last_summary = now
            except Exception as e:
                try:
                    f.write(json.dumps({
                        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "error": repr(e),
                    }) + "\n")
                except Exception:
                    pass
            idx += 1
            # sleep in short chunks so SIGTERM is responsive
            slept = 0
            while slept < INTERVAL_S and not stop["flag"]:
                time.sleep(min(1, INTERVAL_S - slept))
                slept += 1


if __name__ == "__main__":
    main()
