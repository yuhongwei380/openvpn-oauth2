#!/bin/bash
set -e

# 参数处理
CLIENT_NAME=${1:-client}
OUTPUT_DIR=${2:-/etc/openvpn/client-configs}
OVPN_REMOTE_HOST=${3:-${OVPN_REMOTE_HOST:-localhost}}

echo "🔧 生成客户端配置: $CLIENT_NAME"

# 创建输出目录
mkdir -p "$OUTPUT_DIR"

# 读取CA证书内容
if [ -f "/etc/openvpn/certs/ca.crt" ]; then
    export CA_CERT_CONTENT=$(cat /etc/openvpn/certs/ca.crt)
else
    echo "❌ 错误: 找不到CA证书 /etc/openvpn/certs/ca.crt"
    exit 1
fi

# 设置环境变量
export OVPN_PROTO=${OVPN_PROTO:-udp}
export OVPN_PORT=${OVPN_PORT:-1194}
export OVPN_REMOTE_HOST=${OVPN_REMOTE_HOST}
export OVPN_DNS_IPV4=${OVPN_DNS_IPV4:-8.8.8.8}

# 处理IPv6 DNS（如果启用）
if [ "$OVPN_IPV6_ENABLE" = "true" ] && [ -n "$OVPN_DNS_IPV6" ]; then
    export OVPN_DNS_IPV6_CONFIG="dhcp-option DNS $OVPN_DNS_IPV6"
else
    export OVPN_DNS_IPV6_CONFIG=""
fi

# 生成客户端配置文件
envsubst '$OVPN_PROTO $OVPN_PORT $OVPN_REMOTE_HOST $OVPN_DNS_IPV4 $OVPN_DNS_IPV6_CONFIG $CA_CERT_CONTENT' < /etc/openvpn/client.conf.template > "$OUTPUT_DIR/$CLIENT_NAME.ovpn"

echo "✅ 客户端配置已生成: $OUTPUT_DIR/$CLIENT_NAME.ovpn"
echo "📋 使用方法:"
echo "   docker cp openvpn-ldap:/etc/openvpn/client-configs/$CLIENT_NAME.ovpn ./"
