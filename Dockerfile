# MetaScout — web UI image (also runs the REST API, see below).
#
# Bundles everything the *optional* extras need too (content-scan,
# visual-signature, ocr, api) so the image works fully out of the box, no
# separate `pip install` step for anyone using it. That does mean this is a
# heavier image than a bare-metal `pip install metascout` (ImageMagick +
# Ghostscript alone add ~150-250MB, Tesseract another chunk on top) — a
# deliberate "batteries included" tradeoff for a container people pull/build
# once rather than manage dependencies for.
#
# Build:  docker build -t metascout .
# Run (web UI):  docker run --rm -p 127.0.0.1:8765:8765 -v "$(pwd)/metascout_output:/data" metascout
# Run (REST API), overriding the default CMD:
#   docker run --rm -p 127.0.0.1:8000:8000 -v "$(pwd)/metascout_output:/data" metascout \
#     api --host 0.0.0.0 --port 8000 --output-dir /data
# (see the README's Docker section for the full picture, including the
# --host 0.0.0.0 / authentication warning — this image has none built in.)

FROM python:3.12-slim

LABEL org.opencontainers.image.title="MetaScout" \
      org.opencontainers.image.description="Open-source document discovery and metadata reconnaissance tool" \
      org.opencontainers.image.source="https://github.com/gorkemguler/MetaScout" \
      org.opencontainers.image.licenses="MIT"

# - libimage-exiftool-perl: required for all metadata extraction (core feature, not optional)
# - imagemagick + ghostscript: required for --visual-signature and the OCR
#   fallback (see README) — included here so both work without a second
#   manual install step; Wand (the Python binding) delegates PDF
#   rasterization to Ghostscript specifically, ImageMagick alone isn't
#   enough (confirmed while building that feature — see the "Visual (wet)
#   signature detection" README section).
# - tesseract-ocr: the OCR engine itself, used automatically as a fallback
#   for scanned/image-only PDF pages when --scan-content runs (no separate
#   flag — just needs the [ocr] extra + this binary to be present).
# - build-essential: opencv-python/scikit-image/numpy (visual-signature's
#   own dependencies) ship prebuilt wheels for most platforms, but not
#   reliably every one (e.g. some arm64 hosts) — kept as a fallback so the
#   pip install below doesn't fail outright if pip has to compile from
#   source on yours.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libimage-exiftool-perl \
        imagemagick \
        ghostscript \
        tesseract-ocr \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy only what the build needs first, so dependency installation is cached
# across rebuilds that only touch application code.
COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir '.[content-scan,visual-signature,ocr,api]'

# Scan output (report.html/report.json/downloads/) lives here — mount a
# volume at /data to get results back out onto the host and keep them
# across container restarts.
RUN mkdir -p /data
VOLUME /data

# 8765 (web UI) is the default CMD below; 8000 (REST API, `metascout api`)
# is only used if you override CMD — both are declared so either works
# without editing this file.
EXPOSE 8765 8000

ENTRYPOINT ["metascout"]
# --host 0.0.0.0 so the port is reachable from outside the container at
# all (127.0.0.1, the CLI's own default, would only be reachable from
# inside the container itself). This is *not* the same as being reachable
# from outside the host — that depends entirely on how you publish the
# port with `docker run -p` / `ports:` in compose. See the README: bind to
# 127.0.0.1 on the host side unless you've put an authenticating proxy in
# front of this — neither the web UI nor the API has a login of any kind.
CMD ["web", "--host", "0.0.0.0", "--port", "8765", "--output-dir", "/data", "--no-open-browser"]
