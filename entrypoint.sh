#!/bin/bash
set -e

# ==============================================
# 证书处理逻辑（自动生成或使用外部挂载）
# ==============================================
CERT_DIR="/etc/openvpn/certs"
mkdir -p "$CERT_DIR"

if [ "$GENERATE_CERTS" = "true" ]; then
  # 检查是否已存在证书且不需要强制重新生成
  if [ -f "$CERT_DIR/ca.crt" ] && [ "$FORCE_REGENERATE" != "true" ]; then
    echo "🔐 使用现有证书: $CERT_DIR/"
  else
    echo "🔐 生成新证书（10年有效期）..."
    /usr/local/bin/generate-certs.sh
    echo "✅ 证书生成完成"
  fi
else
  echo "🔐 禁用自动证书生成（GENERATE_CERTS=false）"
  # 验证必要的证书文件是否存在
  REQUIRED_CERTS=("ca.crt" "server.crt" "server.key" "dh.pem")
  for cert in "${REQUIRED_CERTS[@]}"; do
    if [ ! -f "$CERT_DIR/$cert" ]; then
      echo "❌ 错误: 缺少必需证书文件: $CERT_DIR/$cert"
      exit 1
    fi
  done
fi

# ==============================================
# 配置模板渲染（OpenVPN）
# ==============================================
echo "📝 生成配置文件..."

# 处理IPv6相关变量（如果启用）
if [ "$OVPN_IPV6_ENABLE" = "true" ]; then
  export OVPN_IPV6_CONFIG="server-ipv6 $OVPN_IPV6_NETWORK"
  export OVPN_IPV6_ROUTE="push \"route-ipv6 $OVPN_IPV6_ROUTE\""
  export OVPN_IPV6_DNS="push \"dhcp-option DNS $OVPN_DNS_IPV6\""
  export OVPN_IPV6_PUSH_SUBNET="push \"route-ipv6 $OVPN_IPV6_NETWORK\""
  export OVPN_IPV6_INTERNAL_ROUTES0="push \"route-ipv6 $OVPN_IPV6_INT_NETWORK0\""
  export OVPN_IPV6_INTERNAL_ROUTES1="push \"route-ipv6 $OVPN_IPV6_INT_NETWORK1\""
  export OVPN_IPV6_INTERNAL_ROUTES2="push \"route-ipv6 $OVPN_IPV6_INT_NETWORK2\""
else
  export OVPN_IPV6_CONFIG=""
  export OVPN_IPV6_ROUTE=""
  export OVPN_IPV6_DNS=""
  export OVPN_IPV6_PUSH_SUBNET=""
  export OVPN_IPV6_INTERNAL_ROUTES0=""
  export OVPN_IPV6_INTERNAL_ROUTES1=""
  export OVPN_IPV6_INTERNAL_ROUTES2=""
fi

# 渲染OpenVPN配置
envsubst '$OVPN_PORT $OVPN_PROTO $OVPN_DEV $OVPN_CA_CERT $OVPN_SERVER_CERT $OVPN_SERVER_KEY $OVPN_DH_PEM $OVPN_NETWORK $OVPN_NETMASK $OVPN_DNS_IPV4 $OVPN_IPV6_CONFIG $OVPN_IPV6_ROUTE $OVPN_IPV6_DNS $OVPN_CIPHER $OVPN_IPV6_PUSH_SUBNET $OVPN_IPV6_INTERNAL_ROUTES0 $OVPN_IPV6_INTERNAL_ROUTES1 $OVPN_IPV6_INTERNAL_ROUTES2' < /etc/openvpn/server.conf.template > /etc/openvpn/server.conf

# ==============================================
# OAuth2 配置文件生成
# ==============================================
echo "🔐 生成 OAuth2 配置文件..."

# 创建 sysconfig 目录
mkdir -p /etc/sysconfig

# 生成 OAuth2 配置文件
cat <<EOF > /etc/sysconfig/openvpn-auth-oauth2
CONFIG_OAUTH2_ISSUER=${OAUTH2_ISSUER:-"https://login.microsoftonline.com/<tenant-id>/v2.0"}
CONFIG_OAUTH2_CLIENT_ID=${OAUTH2_CLIENT_ID}
CONFIG_OAUTH2_CLIENT_SECRET=${OAUTH2_CLIENT_SECRET}
CONFIG_HTTP_SECRET=${OAUTH2_HTTP_SECRET}
CONFIG_HTTP_BASEURL=${OAUTH2_HTTP_BASEURL}
CONFIG_HTTP_LISTEN=${OAUTH2_HTTP_LISTEN:-":9000"}
CONFIG_OPENVPN_ADDR=${OAUTH2_OPENVPN_ADDR:-"unix:///run/openvpn/server.sock"}
CONFIG_OPENVPN_PASSWORD=${OAUTH2_OPENVPN_PASSWORD:-"admin"}
EOF

echo "✅ OAuth2 配置文件生成完成"

# ==============================================
# 网络配置（IPv4/IPv6 NAT和转发）
# ==============================================
echo "🌐 配置网络规则..."

# 启用内核转发
sysctl -w net.ipv4.ip_forward=1
[ "$OVPN_IPV6_ENABLE" = "true" ] && sysctl -w net.ipv6.conf.all.forwarding=1

# IPv4 NAT规则
if [ "$ENABLE_IPV4_NAT" = "true" ]; then
  iptables -t nat -A POSTROUTING -s "$OVPN_NETWORK/$OVPN_NETMASK" -o eth0 -j MASQUERADE
  iptables -A FORWARD -d "$OVPN_NETWORK/$OVPN_NETMASK" -j ACCEPT
  iptables -A FORWARD -s "$OVPN_NETWORK/$OVPN_NETMASK" -j ACCEPT
  iptables -A INPUT -p "$OVPN_PROTO" --dport "$OVPN_PORT" -j ACCEPT
  echo "🔗 已启用IPv4 NAT规则"
fi

# IPv6 NAT规则（如果启用IPv6）
if [ "$OVPN_IPV6_ENABLE" = "true" ] && [ "$ENABLE_IPV6_NAT" = "true" ]; then
  ip6tables -t nat -A POSTROUTING -s "$OVPN_IPV6_NETWORK" -o eth0 -j MASQUERADE
  ip6tables -A FORWARD -d "$OVPN_IPV6_NETWORK" -j ACCEPT
  ip6tables -A FORWARD -s "$OVPN_IPV6_NETWORK" -j ACCEPT
  
  echo "🔗 已启用IPv6 NAT规则"
fi

# ==============================================
# 权限修复
# ==============================================
chown -R nobody:nogroup "$CERT_DIR"
chmod 600 "$CERT_DIR/"*.key "$CERT_DIR/ta.key" 2>/dev/null || true
chmod 644 "$CERT_DIR/"*.crt "$CERT_DIR/dh.pem" 2>/dev/null || true

# 创建运行目录并设置权限
mkdir -p /run/openvpn
chown nobody:nogroup /run/openvpn

# ==============================================
# 创建客户端配置生成功能
# ==============================================
echo "🔧 准备客户端配置生成功能..."

# 创建客户端配置输出目录
mkdir -p /etc/openvpn/client-configs

# 如果需要自动生成默认客户端配置
if [ "$GENERATE_DEFAULT_CLIENT_CONFIG" = "true" ]; then
    echo "📝 生成默认客户端配置..."
    /usr/local/bin/generate-client-config.sh default-client
fi

echo "admin" | tee /etc/openvpn/management-password.txt
chmod 600 /etc/openvpn/management-password.txt
chown root:root /etc/openvpn/management-password.txt

# ==============================================
# 启动 OAuth2 认证服务和 OpenVPN 服务
# ==============================================
echo "🚀 启动 OAuth2 认证服务和 OpenVPN 服务..."

# 创建运行目录
mkdir -p /run/openvpn

# 启动 OAuth2 认证服务（后台运行）
echo "🚀 启动 OAuth2 认证服务..."
/usr/local/bin/openvpn-auth-oauth2 --config /etc/sysconfig/openvpn-auth-oauth2 &

# 等待一下让 OAuth2 服务启动
sleep 3

# 启动 OpenVPN 服务
echo "🚀 启动 OpenVPN 服务..."
exec openvpn /etc/openvpn/server.conf
