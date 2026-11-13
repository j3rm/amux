# Host inotify limit: the "concurrent suites cause false reds" rule

Filed as AH-163 by EmberCoreMigration (org Ember) on 2026-11-13 after
pinning a long-running class of phantom test failures to a single kernel
knob.

## The number

```
/proc/sys/fs/inotify/max_user_instances = 128
/proc/sys/fs/inotify/max_user_watches   = 501004
```

**Instances** is the constraint, not watches. The limit is **per-user**,
shared by every container and process running as `jwesley` on this box.
The kernel default of 128 predates containers-with-many-watchers by
years and distros routinely raise it.

## The failure signature

If a .NET test run reports any of the following, **treat the red as
non-evidence**, not a product defect:

```
IOException: The configured user limit (128) on the number of inotify
  instances has been reached
  at System.IO.FileSystemWatcher.StartRaisingEvents
```

Common surfaces:

- `CrmWebApplicationFactoryDbProviderTests` (any variant)
- `ConfigValidatorTests.VerifyProductionConfig_Throws_*`
- Anything inside `WebApplicationBuilder..ctor` when the host spawns
  a `FileSystemWatcher` for config reload.

**ASP.NET Core hosts install FileSystemWatchers for config reload**, so
every `WebApplicationFactory` / `TestServer` boot consumes inotify
instances. A suite that boots many hosts consumes many. When two or more
agents run suites concurrently, the limit is reached and tests fail with
an error that looks like an arbitrary product defect.

## The rule for agents

**A red that mentions inotify or FileSystemWatcher during a contended
run is NON-EVIDENCE. Re-run on a clear field.**

Before concluding a .NET suite failure is real:

1. Look for the `IOException` + `(128)` line anywhere in the output.
2. Sample concurrent `dotnet test` processes on the host at the time of
   the failure.
3. If either is positive, discard the run and re-serialize.

Dismissing a real red as "probably contention" is just as costly as
chasing a phantom defect. Do (1) and (2) explicitly before deciding.

## The fix, in order of preference

### 1. Raise the limit on the host (preferred, needs sudo)

```
sudo sysctl -w fs.inotify.max_user_instances=1024
echo 'fs.inotify.max_user_instances = 1024' | sudo tee /etc/sysctl.d/90-amux-inotify.conf
```

Persisted under `/etc/sysctl.d/90-amux-inotify.conf` so it survives
reboot. 1024 is the floor; 8192 is safe. No downside at this scale.

Agents inside containers do NOT have sudo and cannot apply this. It is
a Jeremy action on the host.

### 2. Measurement-first, if the limit stays

Current instance count (what the kernel considers used):

```
find /proc/*/fd -lname 'anon_inode:inotify' 2>/dev/null | wc -l
```

Per-process attribution:

```
for pid in $(pgrep -u jwesley -f 'dotnet test\|amux-server'); do
  n=$(ls /proc/$pid/fd 2>/dev/null | xargs -I{} readlink /proc/$pid/fd/{} 2>/dev/null | grep -c anon_inode:inotify)
  echo "$n  $pid  $(ps -o args= -p $pid | head -c 80)"
done | sort -rn | head
```

### 3. Advisory lock (deferred, more invasive)

A shared host-level advisory lock so agent suites serialize instead of
colliding. Several agents have independently built their own
foreign-process gates. A shared one would be cheaper than N private
ones. Not justified until options 1 + 2 fail.

## Related

- [AH-162](../RESUME-HERE.md) same filer, same night, same theme:
  "this host runs several agents concurrently and a few shared resources
  assume it does not." AH-162 was the sweep RMW-on-desc race. This is
  the inotify race.

## amux-server.py's own inotify footprint

`amux-server.py` uses mtime polling for self-reload and for notes-dir
and server.env watching. It does **not** open an inotify instance. The
server is not contributing to the 128 count. The pressure comes from
test-host FileSystemWatchers, not from amux itself.
