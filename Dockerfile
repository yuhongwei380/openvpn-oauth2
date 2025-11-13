FROM ubuntu:24.04

# 设置非交互模式，避免 tzdata 配置时的交互提示
ENV TZ=Asia/Shanghai

# 可选：验证时区
RUN date

# 安装依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    openvpn \
    easy-rsa \
    iptables \
    gettext-base \
    iproute2 \
    iputils-ping \
    tcpdump \
    traceroute \
    vim \
    curl \
    gnupg \
    wget \
    ca-certificates  # 确保安装 ca-certificates


# 添加 openvpn-auth-oauth2 的 apt 源并安装
WORKDIR /tmp
# 下载 .deb 包
RUN wget https://github.com/jkroepke/openvpn-auth-oauth2/releases/download/v1.26.2/openvpn-auth-oauth2_1.26.2_linux_amd64.deb && \
    # 安装 .deb 包
    dpkg -i openvpn-auth-oauth2_1.26.2_linux_amd64.deb && \
    # 清理下载的 .deb 文件以减小镜像大小
    rm openvpn-auth-oauth2_1.26.2_linux_amd64.deb

# 如果需要，可以继续后续的配置步骤...

# 创建目录结构
RUN mkdir -p /etc/openvpn/certs \
    /etc/openvpn/auth \
    /etc/openvpn/client-configs \
    /usr/local/bin \
    /etc/sysconfig
    
# 下载并解压 openvpn-auth-oauth2
RUN cd /tmp/openvpn-oauth2 && \
    wget https://github.com/jkroepke/openvpn-auth-oauth2/releases/download/v1.25.2/openvpn-auth-oauth2_1.25.2_linux_amd64.tar.xz && \
    tar xf openvpn-auth-oauth2_1.25.2_linux_amd64.tar.xz && \
    cp openvpn-auth-oauth2 /usr/local/bin/ && \
    chmod +x /usr/local/bin/openvpn-auth-oauth2 && \
    rm -rf /tmp/openvpn-oauth2

# 添加配置文件和脚本
COPY entrypoint.sh /usr/local/bin/
COPY configs/server.conf.template /etc/openvpn/
COPY configs/client.conf.template /etc/openvpn/

# 证书生成脚本
COPY scripts/generate-certs.sh /usr/local/bin/
COPY scripts/generate-client-config.sh /usr/local/bin/

# 设置权限
RUN chmod +x /usr/local/bin/entrypoint.sh \
    && chmod +x /usr/local/bin/generate-certs.sh \
    && chmod +x /usr/local/bin/generate-client-config.sh

# 开放VPN端口
EXPOSE 1194/udp

# 持久化存储
VOLUME ["/etc/openvpn/certs"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
