FROM caddy:latest

RUN apk add --no-cache nss-tools

COPY Caddyfile /etc/caddy/Caddyfile
