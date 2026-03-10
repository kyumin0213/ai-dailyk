#!/usr/bin/env bash
# DailyK AI Newsroom — 서버 종료 스크립트

cd "$(dirname "$0")"

if [ ! -f .server.pid ]; then
  echo "실행 중인 서버 없음 (.server.pid 없음)"
  exit 0
fi

echo "서버 종료 중..."
while IFS= read -r pid; do
  if kill "$pid" 2>/dev/null; then
    echo "  PID $pid 종료"
  else
    echo "  PID $pid 이미 종료됨"
  fi
done < .server.pid
rm .server.pid
echo "완료"
