#!/bin/bash

CERT_DIR="/etc/openvpn/certs"
EASYRSA_PKI="$CERT_DIR/pki"
# 指定 easyrsa 脚本的完整路径
EASYRSA_PATH="/usr/share/easy-rsa/easyrsa"

# 检查 easyrsa 脚本是否存在
if [ ! -x "$EASYRSA_PATH" ]; then
  echo "错误: 未找到 easyrsa 脚本 at $EASYRSA_PATH"
  echo "请确认 'easy-rsa' 包已安装: apt-get install easy-rsa"
  exit 1
fi

# 初始化PKI
$EASYRSA_PATH --pki-dir="$EASYRSA_PKI" init-pki

# 生成CA（10年有效期）
$EASYRSA_PATH --pki-dir="$EASYRSA_PKI" --batch --days=3650 build-ca nopass

# 生成服务器证书（10年）
$EASYRSA_PATH --pki-dir="$EASYRSA_PKI" --batch --days=3650 build-server-full server nopass

# 生成DH参数
openssl dhparam -out "$CERT_DIR/dh.pem" 2048

# 生成TLS密钥
openvpn --genkey secret "$CERT_DIR/ta.key"

# 设置权限
chmod 600 "$CERT_DIR/"*.key "$CERT_DIR/ta.key"
chmod 644 "$CERT_DIR/"*.crt "$CERT_DIR/dh.pem"
