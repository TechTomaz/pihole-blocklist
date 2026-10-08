FROM python:3.12-alpine
WORKDIR /app
COPY blocklist.py .
COPY lists/ ./lists/
# 568 = TrueNAS standardanvändare "apps"
RUN mkdir /data && chown 568:568 /data
USER 568:568
ENV OUTPUT_DIR=/data PORT=8080 REFRESH_HOURS=12 PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=5s --start-period=120s \
  CMD wget -qO- http://127.0.0.1:8080/health || exit 1
CMD ["python3", "blocklist.py", "serve"]
