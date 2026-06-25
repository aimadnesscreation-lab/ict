#!/usr/bin/env bash
# 24-Hour Server Health Monitor
# Runs in background, logs health/signals/diagnostics every hour.
# Run: nohup bash monitor_24h.sh &
# Check: cat /tmp/ict_24h_monitor.log

LOGFILE="/tmp/ict_24h_monitor.log"
API="http://localhost:8000"

echo "=== ICT 24-Hour Monitor started at $(date -u) ===" > "$LOGFILE"
echo "Monitoring server at $API" >> "$LOGFILE"

start_epoch=$(date +%s)
end_epoch=$((start_epoch + 86400))  # 24 hours from now

# Check every hour (3600 seconds)
while [ "$(date +%s)" -lt "$end_epoch" ]; do
    echo "" >> "$LOGFILE"
    echo "--- Snapshot $(date -u '+%Y-%m-%d %H:%M:%S UTC') ---" >> "$LOGFILE"
    
    # Health check
    health=$(curl -s "$API/api/health" 2>/dev/null)
    if [ -z "$health" ]; then
        echo "SERVER_UNREACHABLE" >> "$LOGFILE"
    else
        echo "$health" | python3 -m json.tool 2>/dev/null >> "$LOGFILE"
    fi
    
    # Signals (top 3)
    signals=$(curl -s "$API/signals?limit=3" 2>/dev/null)
    if [ -n "$signals" ] && [ "$signals" != "[]" ]; then
        echo "--- SIGNALS DETECTED ---" >> "$LOGFILE"
        echo "$signals" | python3 -m json.tool 2>/dev/null >> "$LOGFILE"
    fi
    
    # Diagnostics
    diag=$(curl -s "$API/api/diagnostics" 2>/dev/null)
    if [ -n "$diag" ]; then
        echo "$diag" | python3 -c "
import sys, json
d = json.load(sys.stdin)
w = d.get('websocket', {})
b = d.get('bias', {})
db = d.get('database', {})
r = d.get('risk', {})
print(f\"  WS: {w.get('cycle_count','?')} cycles | Bias: {b.get('htf_bias','?')} | ETH: \${b.get('eth_price',0):.0f}\")
print(f\"  DB trades: {db.get('total_trades',0)} | Daily loss: {r.get('daily_loss_pct',0):.2f}% | Open pos: {r.get('open_positions',0)}\")
" 2>/dev/null >> "$LOGFILE"
    fi
    
    # Check if signals were ever generated
    gen=$(echo "$health" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('total_signals_generated',0))" 2>/dev/null)
    if [ "$gen" != "0" ] && [ -n "$gen" ]; then
        echo ">>> SIGNALS GENERATED: $gen <<<" >> "$LOGFILE"
    fi
    
    # Sleep 1 hour
    sleep 3600
done

echo "" >> "$LOGFILE"
echo "=== MONITORING COMPLETE at $(date -u) ===" >> "$LOGFILE"

# Final summary
echo "" >> "$LOGFILE"
echo "=== FINAL SUMMARY ===" >> "$LOGFILE"
final_health=$(curl -s "$API/api/health" 2>/dev/null)
if [ -n "$final_health" ]; then
    echo "$final_health" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'Uptime: {d.get(\"uptime\",\"?\")}')
print(f'Cycles: {d.get(\"cycle_count\",0)}')
print(f'Signals generated: {d.get(\"total_signals_generated\",0)}')
print(f'Signals kept: {d.get(\"total_signals_kept\",0)}')
print(f'Trades executed: {d.get(\"total_trades_executed\",0)}')
print(f'HTF Bias: {d.get(\"htf_bias\",\"?\")}')
print(f'ETH Price: \${d.get(\"eth_price\",0):.2f}')
print(f'Errors: {d.get(\"last_error_message\",\"none\")}')
" 2>/dev/null >> "$LOGFILE"
fi
