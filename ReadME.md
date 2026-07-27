# OpenVPN OAuth2

通过 OAuth2/OIDC 为 OpenVPN 提供身份认证，并配套独立、常驻的 Web 运维控制台。本项目不包含 LDAP 认证源。

## 服务架构

项目拆分为两个独立服务：

- `vpn-admin`：始终运行的 Web 运维面板，监听 `8080`。
- `openvpn`：常驻的实例控制服务，在容器内独立托管 OpenVPN 与 `openvpn-auth-oauth2` 子进程。

在网页停止 VPN 实例只会结束 OpenVPN 与 OAuth2 子进程，不会停止控制服务或运维面板。因此即使 VPN 实例处于停止或启动失败状态，仍可访问网页查看原因并重新启动。

两个服务通过仅监听 `127.0.0.1:9090` 的内部控制 API 通信。该 API 使用与配置加密密钥相同的令牌进行请求认证，不对外网开放，也不需要挂载 Docker Socket。

## 快速启动

创建 `.env`，只保留两个首次启动所需的秘密：

```bash
cp .env.example .env
openssl rand -base64 32
```

```dotenv
CONFIG_ENCRYPTION_KEY=上一步生成的随机值
WEB_UI_BOOTSTRAP_PASSWORD=首次登录使用的强密码
```

启动两个服务：

```bash
docker compose up -d --build
docker compose ps
```

访问 `http://服务器地址:8080`，首次账号固定为 `admin`。控制台使用项目内置的网页登录页，不会触发浏览器或 Nginx 风格的 Basic Auth 弹窗。登录后可在“系统设置 → 控制台安全”修改正式账号和密码。

登录成功后会创建最长 12 小时的 HttpOnly、SameSite 会话 Cookie；连续登录失败会触发短时限流。右上角的退出按钮可立即结束当前会话。

`CONFIG_ENCRYPTION_KEY` 用于：

- 加密网页保存的 OAuth2 Client Secret、HTTP Secret 和管理接口密码；
- 认证运维面板与 VPN 实例控制服务之间的内部请求。

该密钥必须长期稳定保存。更换或丢失会导致已有密文无法解密。

## 网页控制 VPN 实例

打开“VPN 实例”页面可执行：

- 启动：启动 OpenVPN 与 OAuth2 认证代理；
- 停止：仅停止 VPN 实例，运维面板保持在线；
- 重启：中断现有 VPN 会话并按网页中的最新配置重新启动。

服务、网络、OAuth2 和证书配置保存后，可直接在该页面执行“重启”使其生效，不需要重启 `vpn-admin` 容器。

实例期望状态保存在 `./admin-data/instance-state.json`。如果主动停止实例后重启服务器，实例会保持停止；从网页重新启动后才恢复运行。

## 镜像构建、离线打包与发布

```bash
# 构建 OpenVPN 实例服务镜像
docker build -f Dockerfile -t yuhongwei1997/vpn/openvpn-oauth2:v2.0 .

# 构建管理端镜像
docker build -f admin/Dockerfile -t yuhongwei1997/vpn/openvpn-oauth2-admin:v2.0 .

# 查看构建结果
docker image ls --filter "reference=*openvpn-oauth2*"
```

如需离线部署，可将两个镜像导出为同一个归档文件：

```bash
docker save -o openvpn-oauth2-v2.0-images.tar \
  yuhongwei1997/vpn/openvpn-oauth2:v2.0 \
  yuhongwei1997/vpn/openvpn-oauth2-admin:v2.0
```

如需发布到镜像仓库：

```bash
docker push yuhongwei1997/vpn/openvpn-oauth2:v2.0
docker push yuhongwei1997/vpn/openvpn-oauth2-admin:v2.0
```

在部署服务器上导入镜像并启动服务：

```bash
docker load -i openvpn-oauth2-v2.0-images.tar
docker compose -f docker-compose.yml up -d --force-recreate
```

## 网页配置

“系统设置”覆盖日常运行所需的主要参数：

- OpenVPN 公网地址、端口、协议、设备、地址池、DNS 和数据通道加密；
- IPv4 NAT、IPv6 地址池、DNS、默认路由、内部路由和 IPv6 NAT；
- OAuth2 Issuer、Client ID、Client Secret、回调地址和认证服务监听；
- 证书初始化、默认客户端配置生成和流量审计开关；
- 控制台访问认证、管理员账号和密码。

网页设置保存在 `./admin-data/runtime-settings.json`。敏感字段使用 AES-256-CBC、PBKDF2 和随机盐加密；控制台密码只保存 PBKDF2-SHA256 哈希。管理接口不会返回 Secret、密码或私钥明文。

## 控制台功能

- OpenVPN、OAuth2 认证链路和在线会话总览；
- VPN 实例运行状态及网页启停、重启；
- 连接/断开历史审计、筛选和 CSV 导出；
- VPN 侧 TCP/UDP 目标流量、DNS、TLS SNI 与 HTTP Host 关联；
- 访问目标聚合、目标排行和国家级 GeoIP 归属；
- 证书完整性、有效期检查和 OpenSSL 校验更新；
- 在线生成、下载 `.ovpn` 客户端配置；
- GeoIP 来源、更新频率、审计保留期、品牌和本地文档管理。

## 数据与挂载

| 宿主机目录 | 容器目录 | 内容 |
| --- | --- | --- |
| `./admin-data` | `/etc/openvpn/admin` | SQLite、网页配置、实例期望状态 |
| `./certs` | `/etc/openvpn/certs` | CA、服务端证书、私钥、DH 参数 |
| `./client-configs` | `/etc/openvpn/client-configs` | 网页生成的客户端配置 |
| `./geoip` | `/geoip` | `Country.mmdb` |
| `openvpn-runtime` | `/run/openvpn` | 两个服务共享的状态文件与管理 Socket |

项目使用 `network_mode: host`。OpenVPN 端口由“系统设置”配置；Web 运维面板固定监听 `8080`；实例控制 API 仅监听 `127.0.0.1:9090`。

## 审计边界

流量审计只记录 VPN 解封装后的 TCP/UDP 元数据、方向字节数、DNS 关联域名、TLS SNI 和明文 HTTP Host，不记录 HTTPS 正文、URL 路径或数据包内容。ECH、加密 DNS、长连接和直接 IP 访问可能只能显示目标 IP。

GeoIP 默认使用 `Loyalsoldier/geoip@release/Country.mmdb`，提供国家/地区级归属，不包含城市坐标。来源、更新频率和访问记录保留天数可在流量审计页面配置。

## OAuth2 身份提供商

在 Keycloak、Microsoft Entra ID 或其他 OIDC 提供商中创建机密客户端，并把回调地址设置为：

```text
https://你的认证域名/oauth2/callback
```

之后在“系统设置 → OAuth2 认证”中填写 Issuer、Client ID、Client Secret、回调基础地址和 HTTP 会话 Secret，保存后在“VPN 实例”页面执行重启。

## 运维命令

```bash
docker compose ps
docker compose logs --tail=100 -f vpn-admin
docker compose logs --tail=100 -f openvpn
```

一般情况下不需要执行 `docker compose restart openvpn`；请优先使用网页控制实例。容器级重启只用于升级镜像或修复控制服务本身。
