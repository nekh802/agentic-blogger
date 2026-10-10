#!/bin/zsh
# 매일 07:00·19:00에 맥이 스스로 깨어나게 한다(폰에서 원격으로 쓰는 시간대).
# pmset repeat는 하루 한 번만 되므로, 루트 데몬이 앞으로 4일 치 깨우기를 계속 다시 예약한다.
# 설치: sudo zsh install-wake.sh        제거: sudo zsh install-wake.sh remove
[ "$EUID" = 0 ] || { echo "sudo로 실행하세요: sudo zsh $0" >&2; exit 1; }
LABEL=com.daesin.blogger.wake
BIN=/usr/local/libexec/daesin-blogger-wake
PLIST=/Library/LaunchDaemons/$LABEL.plist

launchctl bootout system/$LABEL 2>/dev/null
if [ "$1" = remove ]; then
  for d in 0 1 2 3 4; do for t in 07:00:00 19:00:00; do
    pmset schedule cancel wake "$(date -v+${d}d "+%m/%d/%y $t")" 2>/dev/null
  done; done
  rm -f "$BIN" "$PLIST"
  echo "제거했습니다"; exit 0
fi

mkdir -p "${BIN:h}"
cat > "$BIN" <<'EOF'
#!/bin/zsh
now=$(date +%s)
for d in 0 1 2 3; do for t in 07:00:00 19:00:00; do
  ts=$(date -v+${d}d "+%m/%d/%y $t")
  (( $(date -j -f "%m/%d/%y %H:%M:%S" "$ts" +%s) > now )) || continue
  pmset schedule cancel wake "$ts" 2>/dev/null   # 중복 예약 방지
  pmset schedule wake "$ts"
done; done
EOF
chown root:wheel "$BIN"; chmod 755 "$BIN"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$BIN</string></array>
  <key>RunAtLoad</key><true/>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Hour</key><integer>7</integer><key>Minute</key><integer>5</integer></dict>
    <dict><key>Hour</key><integer>19</integer><key>Minute</key><integer>5</integer></dict>
  </array>
</dict>
</plist>
EOF
chown root:wheel "$PLIST"; chmod 644 "$PLIST"
launchctl bootstrap system "$PLIST" && sleep 2 && pmset -g sched
