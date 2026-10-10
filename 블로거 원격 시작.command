#!/bin/zsh
# 수동 시작용. 평소에는 LaunchAgent(com.daesin.blogger.remote)가 켜 두므로 실행할 필요가 없다 — 같이 켜면 서버가 둘이 된다.
exec "${0:A:h}/remote.sh"
