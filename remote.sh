#!/bin/zsh
# 휴대폰 Claude 앱에서 이 폴더로 언제든 새 세션을 열 수 있게 Remote Control 서버를 띄운다.
# 로그인 시 LaunchAgent(com.daesin.blogger.remote)가 실행한다. 실행 중에는 맥이 잠들지 않는다(전원 연결 시).
cd "${0:A:h}"
CLAUDE=$(command -v claude || ls -d ~/.vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude 2>/dev/null | sort -V | tail -1)
[ -x "$CLAUDE" ] || { echo "claude 실행 파일을 찾지 못했습니다" >&2; exit 1; }
exec caffeinate -s "$CLAUDE" remote-control --name "대신 블로거"
