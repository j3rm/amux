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

# Claude Code CLI, installed globally so every session's HOME can use it.
# Postinstall downloads the platform-native binary — must run (do NOT use
# --ignore-scripts or you get "Error: claude native binary not installed" at
# first invocation).
RUN npm install -g @anthropic-ai/claude-code

# Force tmux's socket dir off /tmp so it can't accidentally merge with the
# host's tmux daemon if a product spec ever bind-mounts /tmp. Tmux uses
# $TMUX_TMPDIR/tmux-<uid>/default; anywhere-but-/tmp keeps container and
# host daemons distinct even under sloppy mount configs. Set + chmod BEFORE
# the amux user switch so root can write /run/tmux.
ENV TMUX_TMPDIR=/run/tmux
RUN mkdir -p /run/tmux && chmod 0777 /run/tmux

# Uid 1000 = jwesley on host, so bind-mounted files owned by jwesley are
# read/write to the container process without any chown dance.
RUN useradd -m -s /bin/bash -u 1000 amux
USER amux
WORKDIR /home/amux

# Per-session HOMEs will be bind-mounted at /homes/<session-name>/ by the
# host's ensure_product_container() step. Nothing to prep here — the mount
# creates the dir at run time.

# tini is pid 1 to reap zombies from all the `docker exec` children. tail keeps
# the container up until the host explicitly stops it (product idle).
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["tail", "-f", "/dev/null"]
