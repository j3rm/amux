#!/bin/sh
# One-shot confirmation script: checks whether SCHED-44 fired successfully
# tonight and messages Cypra via channel. Scheduled from amux-helper to
# fire at 23:35 UTC on 2026-07-04, 3 min after the expected 23:32 fire.
AMUX_URL="${AMUX_URL:-https://localhost:8822}"

# Query today's SCHED-44 run
result=$(sqlite3 ~/.amux/amux.db "
SELECT status, substr(note, 1, 300)
FROM schedule_runs
WHERE schedule_id = 'SCHED-44'
  AND ran_at > strftime('%s', 'now', '-2 hours')
ORDER BY ran_at DESC LIMIT 1;
")

if [ -z "$result" ]; then
  msg="SCHED-44 did NOT fire in the last 2 hours. Something is blocking it — check server log around 23:32 UTC and DB state. Fresh regression, not the same class as the run_at/schedule_expr split from earlier."
else
  status=$(echo "$result" | cut -d'|' -f1)
  note=$(echo "$result" | cut -d'|' -f2- | tr '\n' ' ' | head -c 400)
  if [ "$status" = "ok" ]; then
    msg="SCHED-44 fired at 23:32 UTC as expected. Result: $note. Backoff patch + stagger both held; nothing manual needed on my end for 07-04."
  else
    msg="SCHED-44 fired but returned status=$status. Note: $note. Something failed inside the script — check whether it's the same DB-lock class or new."
  fi
fi

# Post to Cypra via channel
python3 - <<PYEOF
import urllib.request, json, ssl, os
ctx = ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
msg = """$msg"""
req = urllib.request.Request(
    f"https://localhost:8822/api/channels/amux-helper/Cypra/messages",
    data=json.dumps({"text": msg}).encode(),
    method="POST",
    headers={"Content-Type":"application/json"},
)
with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
    d = json.loads(r.read())
    print("sent:", d.get("delivery_status"))
PYEOF
