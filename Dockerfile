# newadv-cibil-pdf-engine - example Docker image. Fonts and the CIBIL logo
# ship inside the package (static/), so no font packages are required.
#
# WeasyPrint needs a handful of native libraries (Pango/Cairo/GDK-Pixbuf)
# for text shaping and rasterisation; this installs the Debian packages
# for them. Build:
#
#   docker build -t newadv-cibil-pdf-engine .
#   docker run --rm -v "$PWD/input:/data/in" -v "$PWD/output:/data/out" \
#       newadv-cibil-pdf-engine --input /data/in/sample.json --output /data/out/sample.pdf

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        libffi-dev \
        shared-mime-info \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml requirements.txt ./
COPY newadv_cibil_pdf_engine ./newadv_cibil_pdf_engine
RUN pip install --no-cache-dir .

ENTRYPOINT ["python", "-m", "newadv_cibil_pdf_engine"]
CMD ["--help"]
