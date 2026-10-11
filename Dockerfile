# ---- Kamuflaj oyun sunucusu ----
# Hugging Face Spaces (Docker) icin hazirlanmistir; Koyeb / Render / Railway / Fly
# gibi platformlarda da calisir (hepsi PORT ortam degiskenini kendisi verir).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=7860

# Hugging Face Spaces konteyneri root olmayan kullanici (uid 1000) ile calistirir.
RUN useradd -m -u 1000 user

WORKDIR /app

COPY --chown=user:user requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user:user . .

USER user

# Hugging Face Spaces varsayilan portu 7860'tir (README icindeki app_port ile eslesir).
EXPOSE 7860

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-7860} --proxy-headers --forwarded-allow-ips='*' --ws websockets"]
