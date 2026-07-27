FROM ubuntu:24.04

ENV TZ=Asia/Shanghai \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gettext-base \
    openssl \
    python3 \
    python3-maxminddb \
    tcpdump \
    tshark \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/openvpn-admin

COPY admin /opt/openvpn-admin
COPY ReadME.md /opt/openvpn-admin/README.md
COPY configs/client.conf.template /etc/openvpn/client.conf.template
COPY scripts/generate-client-config.sh /usr/local/bin/generate-client-config.sh

RUN sed -i 's/\r$//' /usr/local/bin/generate-client-config.sh \
    && chmod +x /usr/local/bin/generate-client-config.sh \
    && mkdir -p /etc/openvpn/admin /etc/openvpn/certs \
       /etc/openvpn/client-configs /run/openvpn /geoip

EXPOSE 8080/tcp

ENTRYPOINT ["python3", "/opt/openvpn-admin/server.py"]
