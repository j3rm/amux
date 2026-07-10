# amux-agent-base — long-lived per-product container image.
#
# One container per product runs from this image. The container has no
# long-running process of its own beyond tini+tail; the AMUX server on the host
# uses `docker exec` to spawn `tmux new-session` inside, and each such tmux
# session is one AMUX agent (RTG-Research, iSchedule-Main, etc.).
#
# Per-session isolation is achieved by setting HOME=/homes/<session> at
# `tmux new-session -e HOME=...`, and by bind-mounting the host's
# /opt/amux/homes/<session>/ into the container at /homes/<session>/. Each
# session's ~/.claude/ (OAuth, projects, settings) lives in that per-session
# home — completely isolated from every other session in every other container.
#
# Build:
#   docker build -t amux-agent-base:latest agent-container/
# Verify:
#   docker run --rm amux-agent-base:latest sh -c "tmux -V && claude --version"

FROM python:3.11-slim

# Base tools every agent needs at runtime. openssh-client is here so git can
# use ssh remotes; ca-certificates for TLS.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tini tmux curl git ca-certificates procps openssh-client \
        nodejs npm \
        less jq sqlite3 vim-tiny \
    && rm -rf /var/lib/apt/lists/*

# Claude Code CLI + OpenAI Codex CLI, installed globally so every session's
# HOME can use them. Postinstall downloads platform-native binaries — must
# run (do NOT use --ignore-scripts or you get "Error: claude native binary
# not installed" at first invocation).
# Codex is used by the *-Audit-Codex sessions (RTG-Audit-Codex,
# Ember-Audit-Codex, iSchedule-Audit-Codex, ShareScore-audit).
RUN npm install -g @anthropic-ai/claude-code @openai/codex

# The `amux` CLI lives in the amux repo (host bind-mounts /mnt/gitdata/amux
# read-only into every product container). Symlink it onto PATH so agents
# can call `amux threads reply ...` etc. without knowing the full path.
# The link resolves at runtime once the mount is attached; broken until then,
# which is fine — no session runs before the mount exists.
RUN ln -s /mnt/gitdata/amux/amux /usr/local/bin/amux

# Force tmux's socket dir off /tmp so it can't accidentally merge with the
# host's tmux daemon if a product spec ever bind-mounts /tmp. Tmux uses
# $TMUX_TMPDIR/tmux-<uid>/default; anywhere-but-/tmp keeps container and
# host daemons distinct even under sloppy mount configs. Set + chmod BEFORE
# the amux user switch so root can write /run/tmux.
ENV TMUX_TMPDIR=/run/tmux
RUN mkdir -p /run/tmux && chmod 0777 /run/tmux

# Opt Claude Code out of the fullscreen alternate-screen renderer. Amux drives
# every session through tmux + docker exec; the amux dashboard peek reads the
# tmux capture-pane; SMS/thread webhooks send text via tmux load-buffer. All of
# those rely on Claude Code's UI staying in the terminal's *native* scrollback
# stream, not the alternate-screen buffer. When Claude Code enters alternate
# screen (its default), the pane content Amux captures becomes an empty screen
# with just the input prompt at the bottom — peek text is garbled, /tui default
# has to be re-typed by hand every restart, and clients like the mobile web UI
# see stale/empty screens. Setting this env var globally in the image forces
# native-scrollback mode for every claude spawn in every session in every
# container — no per-session opt-in required, no drift when a session's config
# is reset by /compact or a wipe-cascade.
ENV CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN=1

# Uid 1000 = jwesley on host, so bind-mounted files owned by jwesley are
# read/write to the container process without any chown dance.
RUN useradd -m -s /bin/bash -u 1000 amux

# Hand the global-npm tree to the amux user so `claude` and `codex` can
# auto-update themselves in place without root. Without this, every container
# start emits "✘ Auto-update failed: no write permission to npm prefix" and
# some sessions hard-exit to bash on the failure. `/usr/local/lib/node_modules`
# holds the packages; `/usr/local/bin` holds the CLI shims npm rewrites on
# upgrade. Both need `amux:amux` ownership. Blast radius: an agent could
# npm-install a malicious replacement into its own container image — but
# containers are already discardable per product, and every agent already runs
# `--dangerously-skip-permissions`, so this is not a widening of the trust
# model.
RUN chown -R amux:amux /usr/local/lib/node_modules /usr/local/bin

USER amux
WORKDIR /home/amux

# Per-session HOMEs will be bind-mounted at /homes/<session-name>/ by the
# host's ensure_product_container() step. Nothing to prep here — the mount
# creates the dir at run time.

# tini is pid 1 to reap zombies from all the `docker exec` children. tail keeps
# the container up until the host explicitly stops it (product idle).
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["tail", "-f", "/dev/null"]
