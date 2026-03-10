FROM python:3.11-slim

WORKDIR /app

# 의존성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 복사
COPY api.py writer.py ./
COPY guidelines/ ./guidelines/

# articles 디렉터리 생성 (런타임에 기사 저장)
RUN mkdir -p articles

# Cloud Run은 PORT 환경변수 사용 (기본 8080)
ENV PORT=8080

CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT}"]
