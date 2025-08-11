#!/bin/bash

CERT_DIR="/etc/openvpn/certs"
EASYRSA_PKI="$CERT_DIR/pki"

# 初始化PKI
easyrsa --pki-dir="$EASYRSA_PKI" init-pki

# 生成CA（10年有效期）
easyrsa --pki-dir="$EASYRSA_PKI" --batch --days=3650 build-ca nopass

# 生成服务器证书（10年）
easyrsa --pki-dir="$EASYRSA_PKI" --batch --days=3650 build-server-full server nopass

# 生成DH参数
openssl dhparam -out "$CERT_DIR/dh.pem" 2048

# 生成TLS密钥
openvpn --genkey secret "$CERT_DIR/ta.key"

# 设置权限
chmod 600 "$CERT_DIR/"*.key "$CERT_DIR/ta.key"
chmod 644 "$CERT_DIR/"*.crt "$CERT_DIR/dh.pem"