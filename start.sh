#!/usr/bin/env bash
# DailyK AI Newsroom — 서버 시작 스크립트
# 사용법: ./start.sh
# 종료:   ./stop.sh

set -e
cd "$(dirname "$0")"

mkdir -p logs

# 이미 실행 중인 프로세스 정리
if [ -f .server.pid ]; then
  echo "기존 서버 종료 중..."
  while IFS= read -r pid; do
    kill "$pid" 2>/dev/null && echo "  PID $pid 종료" || true
  done < .server.pid
  rm .server.pid
  sleep 1
fi

# uvicorn (API 서버, port 8000)
echo "uvicorn 시작 (port 8000)..."
nohup python3 -m uvicorn api:app --port 8000 \
  > logs/uvicorn.log 2>&1 &
echo $! >> .server.pid

# http.server (정적 파일, port 8081)
echo "http.server 시작 (port 8081)..."
nohup python3 -m http.server 8081 \
  > logs/httpserver.log 2>&1 &
echo $! >> .server.pid

sleep 1
echo ""
echo "✓ 서버 시작 완료"
echo "  API     → http://localhost:8000"
echo "  Newsroom → http://localhost:8081"
echo ""
echo "로그: tail -f logs/uvicorn.log"
echo "종료: ./stop.sh"
