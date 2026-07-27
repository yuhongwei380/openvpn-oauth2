#!/bin/bash

CERT_DIR="/etc/openvpn/certs"
EASYRSA_DIR="/root/openvpn-ca"
EASYRSA_PKI="$EASYRSA_DIR/pki"

# 创建必要的目录
mkdir -p "$CERT_DIR"

# 如果目录已存在，先清理掉
if [ -d "$EASYRSA_DIR" ]; then
    rm -rf "$EASYRSA_DIR"
fi

# 创建 CA 目录结构
make-cadir "$EASYRSA_DIR"
cd "$EASYRSA_DIR"

# 配置 vars 文件
cat > vars <<EOF
export KEY_COUNTRY="CN"
export KEY_PROVINCE="ZJ"
export KEY_CITY="HZ"
export KEY_ORG="admin"
export KEY_EMAIL="example@test.com"
export KEY_OU="IT"
export KEY_NAME="server"
EOF

# 确保在正确的目录中执行
cd "$EASYRSA_DIR"

# 初始化 PKI
echo "Initializing PKI..."
./easyrsa --pki-dir="$EASYRSA_PKI" init-pki

# 构建 CA（使用 batch 模式避免交互）
echo "Building CA..."
./easyrsa --pki-dir="$EASYRSA_PKI" --batch build-ca nopass

# 生成服务器证书
echo "Building server certificate..."
./easyrsa --pki-dir="$EASYRSA_PKI" --batch build-server-full server nopass

# 生成 Diffie-Hellman 参数
echo "Generating DH parameters..."
./easyrsa --pki-dir="$EASYRSA_PKI" gen-dh

# 生成 HMAC 签名密钥 (TLS auth key)
echo "Generating TLS auth key..."
openvpn --genkey secret "$CERT_DIR/ta.key"

# 设置权限
echo "Setting permissions..."
if [ -d "$EASYRSA_PKI/private/" ] && [ -n "$(ls -A "$EASYRSA_PKI/private/"*.key 2>/dev/null)" ]; then
    chmod 600 "$EASYRSA_PKI/private/"*.key 2>/dev/null || true
fi

if [ -d "$EASYRSA_PKI/issued/" ] && [ -n "$(ls -A "$EASYRSA_PKI/issued/"*.crt 2>/dev/null)" ]; then
    chmod 644 "$EASYRSA_PKI/issued/"*.crt 2>/dev/null || true
fi

if [ -f "$EASYRSA_PKI/ca.crt" ]; then
    chmod 644 "$EASYRSA_PKI/ca.crt"
fi

if [ -f "$EASYRSA_PKI/dh.pem" ]; then
    chmod 644 "$EASYRSA_PKI/dh.pem"
fi

chmod 600 "$CERT_DIR/ta.key"

# 拷贝证书到 /etc/openvpn/certs 目录
echo "Copying certificates to $CERT_DIR directory..."

# 检查并拷贝文件
COPY_SUCCESS=true

if [ -f "$EASYRSA_PKI/ca.crt" ]; then
    cp "$EASYRSA_PKI/ca.crt" "$CERT_DIR/"
    echo "✓ Copied ca.crt"
else
    echo "❌ Missing ca.crt"
    COPY_SUCCESS=false
fi

if [ -f "$EASYRSA_PKI/issued/server.crt" ]; then
    cp "$EASYRSA_PKI/issued/server.crt" "$CERT_DIR/"
    echo "✓ Copied server.crt"
else
    echo "❌ Missing server.crt"
    COPY_SUCCESS=false
fi

if [ -f "$EASYRSA_PKI/private/server.key" ]; then
    cp "$EASYRSA_PKI/private/server.key" "$CERT_DIR/"
    echo "✓ Copied server.key"
else
    echo "❌ Missing server.key"
    COPY_SUCCESS=false
fi

if [ -f "$EASYRSA_PKI/dh.pem" ]; then
    cp "$EASYRSA_PKI/dh.pem" "$CERT_DIR/"
    echo "✓ Copied dh.pem"
else
    echo "❌ Missing dh.pem"
    COPY_SUCCESS=false
fi

if [ "$COPY_SUCCESS" = true ]; then
    echo "✅ All certificates copied successfully to $CERT_DIR!"
else
    echo "❌ Some certificate files are missing!"
    echo "Files in PKI directory:"
    find "$EASYRSA_PKI" -type f 2>/dev/null || echo "PKI directory not found"
fi

# 设置最终权限
chmod 600 "$CERT_DIR/"*.key 2>/dev/null || true
chmod 644 "$CERT_DIR/"*.crt "$CERT_DIR/"*.pem 2>/dev/null || true

# 列出最终生成的文件
echo "Final files in $CERT_DIR:"
ls -la "$CERT_DIR/" 2>/dev/null || echo "Certificate directory not accessible"
