# Dockerfile — serves the BIPES fork as a static site.
# Identical behavior locally and on Railway:
#   local:   docker build -t bipes . && docker run -e PORT=8080 -p 8000:8080 bipes
#   Railway: auto-detected at repo root; Railway injects PORT at runtime.
#
# Uses the official nginx image's template mechanism: any file in
# /etc/nginx/templates/*.template is envsubst-rendered into /etc/nginx/conf.d/
# by the image's own entrypoint at container start. This is how ${PORT}
# gets expanded WITHOUT a shell-form CMD (the documented Railway failure
# mode is exec-form CMD not expanding $PORT — templates avoid CMD entirely).

FROM nginx:1.27-alpine

# Default for local runs; Railway overrides this with its injected PORT.
ENV PORT=8080

COPY deploy/default.conf.template /etc/nginx/templates/default.conf.template
COPY . /usr/share/nginx/html
