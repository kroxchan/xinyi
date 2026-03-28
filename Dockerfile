# =============================================================================
# xinyi Dockerfile — multi-stage build
#
# IMPORTANT: WeChat DB decryption requires macOS native environment (Xcode CLT).
# This Docker image supports the WebUI + RAG pipeline only.
# If you need to decrypt WeChat data, use the native macOS setup instead.
# =============================================================================

FROM python:3.11-slim AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Pre-install heavy dependencies
COPY requirements.txt /tmp/
RUN pip install --no-cache-dir --user -r /tmp/requirements.txt


# ── Runtime stage ──────────────────────────────────────────────────────────

FROM python:3.11-slim

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Copy source code
COPY . /app

# Expose Gradio default port
EXPOSE 7860

# Default command: run the WebUI
CMD ["python", "src/app.py"]
