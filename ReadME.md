# OpenVPN OAuth2

将 OpenVPN、`openvpn-auth-oauth2` 与一体化 Web 管理控制台打包在同一容器中。
本项目仅使用 OAuth2/OIDC 认证，不包含 LDAP 认证源。

## 快速启动

复制并修改最小启动配置：

```bash
cp .env.example .env
openssl rand -base64 32
```

`.env` 只需要两个值：

```dotenv
CONFIG_ENCRYPTION_KEY=至少32字节的随机值
WEB_UI_BOOTSTRAP_PASSWORD=首次登录强密码
```

启动服务：

```bash
docker compose up -d --build
```

访问 `http://服务器地址:8080`，首次账号固定为 `admin`。进入
“系统设置 → 控制台安全”设置正式账号和密码后，
`WEB_UI_BOOTSTRAP_PASSWORD` 可以从 `.env` 删除。

`CONFIG_ENCRYPTION_KEY` 用于加密网页保存的 OAuth2 Client Secret 和 HTTP
会话 Secret，必须长期稳定保存。更换或遗失该密钥会导致已有密文无法解密。

## 网页配置

“系统设置”覆盖日常运行需要的主要参数：

- OpenVPN 公网地址、端口、协议、设备、地址池、DNS 和数据通道加密；
- IPv4 NAT、IPv6 地址池、DNS、默认路由、内部路由和 IPv6 NAT；
- OAuth2 Issuer、Client ID、Client Secret、回调地址和认证服务监听；
- 证书初始化、默认客户端配置生成和流量审计开关；
- 控制台访问认证、管理员账号和密码。

流量采集和控制台安全设置保存后即时生效。OpenVPN、OAuth2、证书初始化及网络
参数会在下次执行以下命令后生效：

```bash
docker compose restart openvpn
```

网页设置保存在 `./admin-data/runtime-settings.json`，敏感字段使用
AES-256-CBC、PBKDF2 和随机盐加密；控制台密码只保存 PBKDF2-SHA256 哈希。
管理接口不会返回 Secret、密码或私钥明文。

## 控制台功能

- OpenVPN、OAuth2 认证链路和在线会话总览；
- 单实例运行状态、服务配置和容器编排边界；
- 连接/断开历史审计、筛选和 CSV 导出；
- VPN 侧 TCP/UDP 目标流量、DNS、TLS SNI 与 HTTP Host 关联；
- 访问目标聚合、目标排行和国家级 GeoIP 归属；
- 证书完整性、有效期检查和 OpenSSL 校验更新；
- 在线生成、下载 `.ovpn` 客户端配置；
- GeoIP 来源、更新频率、审计保留期、品牌和本地文档管理。

## 数据与挂载

| 宿主机目录 | 容器目录 | 内容 |
| --- | --- | --- |
| `./admin-data` | `/etc/openvpn/admin` | SQLite、运行配置、控制台设置 |
| `./certs` | `/etc/openvpn/certs` | CA、服务端证书、私钥、DH 参数 |
| `./geoip` | `/geoip` | `Country.mmdb` |

项目使用 `network_mode: host`。OpenVPN 端口由“系统设置”配置，Web 控制台固定
监听 `8080`，避免修改页面配置后造成管理入口不可达。

## 审计边界

流量审计只记录 VPN 解封装后的 TCP/UDP 元数据、方向字节数、DNS 关联域名、
TLS SNI 和明文 HTTP Host，不记录 HTTPS 正文、URL 路径或数据包内容。ECH、
加密 DNS、长连接和直接 IP 访问可能只能显示目标 IP。

GeoIP 默认使用 `Loyalsoldier/geoip@release/Country.mmdb`，提供国家/地区级
归属，不包含城市坐标。来源、更新频率和访问记录保留天数可在流量审计页面配置。

## OAuth2 身份提供商

在 Keycloak、Microsoft Entra ID 或其他 OIDC 提供商中创建机密客户端，并把
回调地址设置为：

```text
https://你的认证域名/oauth2/callback
```

之后在“系统设置 → OAuth2 认证”中填写 Issuer、Client ID、Client Secret、
回调基础地址和 HTTP 会话 Secret，保存并重启容器。

## 运维命令

```bash
docker compose ps
docker compose logs --tail=100 -f openvpn
docker compose restart openvpn
```
