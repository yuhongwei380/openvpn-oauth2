# Test project,  NO test
# Info about this project

Openvpn Connect to oauth2

https://github.com/jkroepke/openvpn-auth-oauth2



#Using

## 1. docker-compose  with the .env

## 2. get the client profile
```
docker exec openvpn-oauth2 /usr/local/bin/generate-client-config.sh my-client
docker cp openvpn-oauth2:/etc/openvpn/client-configs/my-client.ovpn ./
```

## 3. support the IPV4 & IPV6

introduce：
`10.7.0.0/16`  is your vpn network
`fd00:2024:dbf:0000:2290::/80` is your docker network for IPV6

daemon.json
```
"ipv6": true,
"fixed-cidr-v6": "fd00:2024:dbf:0000:2290::/80"

```

## 4. Get the Client Config
```
docker cp openvpn-oauth2:/etc/openvpn/client-configs/default-client.ovpn ./
```

## 5.Setting the NAT
NAT from vm with docker
```
sudo iptables -t nat -A POSTROUTING -s 10.7.0.0/16 -o eth0 -j MASQUERADE
sudo ip6tables -t nat -A POSTROUTING -s fd00:2024:dbf:0000:2290::/80 -o  eth0 -j MASQUERADE
```
删除 iptables
```
sudo ip6tables -t nat -D POSTROUTING -s fd12:3456:789a::/64 -o eth0 -j MASQUERADE
```


FOR Keycloak
```
Register an App with Keycloak
向 Keycloak 注册应用程序
Sign in to your admin account on the Keycloak admin console.
在 Keycloak 管理控制台上登录您的管理员帐户。
Choose an existing realm or create a new one.
选择现有领域或创建新领域。
Create a new client:
创建新客户端：
Set the Client ID as openvpn-auth-oauth2.
将客户端 ID 设置为 openvpn-auth-oauth2。
Set the Client Type as OpenID Connect.
将客户端类型设置为 OpenID Connect。
Name the client as openvpn-auth-oauth2.
将客户端命名为 openvpn-auth-oauth2。
In the capability configuration page, enable 'Client authentication' and 'Standard flow' for the Authentication flow. Make sure 'Authorization' is turned off.
在功能配置页中，为身份验证流启用“客户端身份验证”和“标准流”。确保“授权”已关闭。
In the login settings page, set the following values:
在登录设置页面中，设置以下值：
Root URL: https://openvpn-auth-oauth2.example.com  根网址： https://openvpn-auth-oauth2.example.com
Valid Redirect URIs: https://openvpn-auth-oauth2.example.com/oauth2/callback
有效的重定向 URI： https://openvpn-auth-oauth2.example.com/oauth2/callback
Web Origins: https://openvpn-auth-oauth2.example.com  网络起源： https://openvpn-auth-oauth2.example.com
Click 'Save'.  单击“保存”。
Navigate to the 'Credentials' tab and note down the Client ID and Client Secret.
导航到“凭据”选项卡并记下客户端 ID 和客户端密码。
```

