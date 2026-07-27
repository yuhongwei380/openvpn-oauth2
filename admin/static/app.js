const state = {
  status: null, connections: [], connectionEvents: [], profiles: [], traffic: null,
  targets: [], branding: null, settings: null, view: "overview", trafficTimer: null,
};
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  })[char]);
}

function formatBytes(value) {
  const bytes = Number(value) || 0;
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / (1024 ** index)).toFixed(index > 1 ? 1 : 0)} ${units[index]}`;
}

function formatDuration(seconds) {
  seconds = Math.max(0, Number(seconds) || 0);
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days) return `${days}天 ${hours}小时`;
  if (hours) return `${hours}小时 ${minutes}分`;
  return `${minutes}分钟`;
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  }).format(date);
}

function initials(name) {
  const clean = String(name || "?").split("@")[0].replace(/[^a-zA-Z0-9]/g, "");
  return (clean.slice(0, 2) || "?").toUpperCase();
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `请求失败 (${response.status})`);
  return payload;
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("visible");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove("visible"), 2600);
}

function showView(name) {
  state.view = name;
  $$(".view").forEach((view) => view.classList.toggle("active", view.id === `view-${name}`));
  $$(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === name));
  const active = $(`.nav-item[data-view="${name}"]`);
  $("#currentPage").textContent = active?.querySelector("span")?.textContent || "";
  $("#sidebar").classList.remove("open");
  $("#sidebarBackdrop").classList.remove("visible");
  history.replaceState(null, "", `#${name}`);
  if (name === "profiles") loadProfiles();
  if (name === "instance") loadInstance();
  if (name === "connections") loadConnectionAudit();
  if (name === "traffic") loadTraffic();
  if (name === "certificates") loadCertificates();
  if (name === "docs") loadDocs();
  if (name === "settings") loadSystemSettings();
  if (name === "branding") loadBranding();
  configureTrafficTimer();
}

function connectionRow(item, compact = false) {
  const username = escapeHtml(item.username || "未知用户");
  if (compact) {
    return `<div class="connection-row">
      <div class="user-cell"><span class="user-avatar">${initials(item.username)}</span><span><strong>${username}</strong><small>${escapeHtml(item.realAddress || "来源地址未知")}</small></span></div>
      <span>${escapeHtml(item.virtualAddress || "—")}</span>
      <span>${formatBytes(item.bytesReceived + item.bytesSent)}</span>
      <span class="online-label">● 在线</span>
    </div>`;
  }
  return `<tr><td>${username}</td><td>${escapeHtml(item.virtualAddress || item.virtualIpv6Address || "—")}</td>
    <td>${escapeHtml(item.realAddress || "—")}</td><td>${formatBytes(item.bytesReceived)}</td>
    <td>${formatBytes(item.bytesSent)}</td><td>${formatDate(item.connectedAt)}</td><td><span class="status-badge">在线</span></td></tr>`;
}

function renderLivePreview() {
  const preview = state.connections.slice(0, 4);
  $("#connectionPreview").classList.remove("loading-block");
  $("#connectionPreview").innerHTML = preview.length
    ? preview.map((item) => connectionRow(item, true)).join("")
    : `<div class="empty-state visible"><span><svg><use href="#icon-users"/></svg></span><h3>暂无在线连接</h3><p>新的认证会话会自动出现在这里。</p></div>`;
}

function auditEventRow(item) {
  const badgeClass = item.event === "connect" ? "status-badge" : "event-badge disconnect";
  return `<tr><td>${formatDate(item.timestamp)}</td><td><span class="${badgeClass}">${item.event === "connect" ? "连接" : "断开"}</span></td>
    <td>${escapeHtml(item.username || "未知用户")}</td><td class="technical">${escapeHtml(item.realAddress || "—")}</td>
    <td class="technical">${escapeHtml(item.virtualAddress || "—")}</td><td>${formatBytes(item.bytesReceived)}</td>
    <td>${formatBytes(item.bytesSent)}</td><td>${formatDuration(item.durationSeconds)}</td></tr>`;
}

function renderConnectionAudit() {
  $("#connectionsTable").innerHTML = state.connectionEvents.map(auditEventRow).join("");
  $("#connectionsEmpty").classList.toggle("visible", state.connectionEvents.length === 0);
  $("#connectionCount").textContent = `${state.connectionEvents.length} 条记录`;
}

function connectionQuery() {
  const params = new URLSearchParams({
    keyword: $("#connectionSearch")?.value.trim() || "",
    event: $("#connectionEvent")?.value || "",
    range: $("#connectionRange")?.value || "24h",
  });
  return params;
}

async function loadConnectionAudit() {
  try {
    const params = connectionQuery();
    const payload = await api(`/api/audit/connections?${params}`);
    state.connectionEvents = payload.events || [];
    $("#connectionExport").href = `/api/audit/connections.csv?${params}`;
    renderConnectionAudit();
  } catch (error) {
    showToast(error.message);
  }
}

function renderStatus(payload) {
  state.status = payload;
  state.connections = payload.status.clients || [];
  $("#metricConnections").textContent = payload.connections;
  $("#metricReceived").textContent = formatBytes(payload.bytesReceived);
  $("#metricSent").textContent = formatBytes(payload.bytesSent);
  $("#metricUptime").textContent = formatDuration(payload.uptimeSeconds);
  $("#sidebarUptime").textContent = `已运行 ${formatDuration(payload.uptimeSeconds)}`;
  $("#navConnectionCount").textContent = payload.connections;

  const server = payload.config.server;
  const oauth2 = payload.config.oauth2;
  $("#serverHost").textContent = server.remoteHost || "未配置";
  $("#serverPort").textContent = server.port;
  $("#serverNetwork").textContent = `${server.network} / ${server.netmask}`;
  $("#serverDns").textContent = server.dns || "未配置";
  $("#protocolTag").textContent = String(server.protocol).toUpperCase();
  $("#profileHost").value ||= server.remoteHost;
  $("#oauthNodeState").textContent = oauth2.configured ? "已配置" : "待配置";
  $("#tunnelDescription").textContent = oauth2.configured
    ? "身份提供商、认证代理和 OpenVPN 服务正在协同工作。"
    : "OpenVPN 已运行，但 OAuth2 参数尚未完整配置。";
  renderLivePreview();
}

async function refreshStatus(showFeedback = false) {
  const button = $("#refreshButton");
  button.disabled = true;
  try {
    renderStatus(await api("/api/status"));
    $("#lastRefresh").textContent = `更新于 ${new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date())}`;
    if (showFeedback) showToast("运行状态已刷新");
  } catch (error) {
    showToast(error.message);
  } finally {
    button.disabled = false;
  }
}

async function loadInstance() {
  try {
    const instance = await api("/api/instance");
    $("#instanceOnline").innerHTML = `${instance.online} <small>在线</small>`;
    $("#instanceCertificateState").textContent = instance.certificate.ready ? "材料完整" : "材料不完整";
    const config = instance.config;
    $("#instanceFacts").innerHTML = [
      ["服务端点", `${config.remoteHost || "未配置"}:${config.port}`],
      ["协议 / 设备", `${String(config.protocol).toUpperCase()} / ${config.device}`],
      ["IPv4 地址池", `${config.network} / ${config.netmask}`],
      ["OAuth2 认证", state.status?.config.oauth2.configured ? "已配置" : "待配置"],
    ].map(([label, value]) => `<div><span>${label}</span><strong title="${escapeHtml(value)}">${escapeHtml(value)}</strong></div>`).join("");
  } catch (error) {
    showToast(error.message);
  }
}

function trafficQuery() {
  return new URLSearchParams({
    keyword: $("#trafficSearch")?.value.trim() || "",
    range: $("#trafficRange")?.value || "24h",
  });
}

function renderTraffic(payload) {
  state.traffic = payload;
  const summary = payload.summary;
  $("#trafficTotal").textContent = formatBytes(summary.uploadBytes + summary.downloadBytes);
  $("#trafficDownload").textContent = formatBytes(summary.downloadBytes);
  $("#trafficUpload").textContent = formatBytes(summary.uploadBytes);
  $("#trafficConnections").textContent = summary.connections;
  $("#trafficTargets").textContent = summary.targets;
  $("#trafficUsers").textContent = summary.users;
  const capture = $("#captureBadge");
  capture.className = `capture-badge ${payload.capture.state}`;
  capture.textContent = ({ running: "正在采集", waiting: "等待采集", disabled: "已禁用", failed: "采集失败" })[payload.capture.state] || payload.capture.state;
  capture.title = payload.capture.message;

  $("#trafficTable").innerHTML = payload.recent.map((item) => `<tr>
    <td>${formatDate(item.timestamp)}</td><td>${escapeHtml(item.username || "未识别")}</td>
    <td class="target-cell"><strong>${escapeHtml(item.domain || item.targetIp)}</strong><small>${escapeHtml(item.targetIp)}</small></td>
    <td>${item.targetPort || "—"}</td><td>${escapeHtml(item.protocol)}</td><td>${formatBytes(item.uploadBytes)}</td>
    <td>${formatBytes(item.downloadBytes)}</td><td>${item.connections}</td></tr>`).join("");
  $("#trafficRecordCount").textContent = `${payload.recent.length} 条记录`;
  $("#trafficEmpty").classList.toggle("visible", payload.recent.length === 0);

  const maxDestination = Math.max(...payload.destinations.map((item) => item.upload + item.download), 1);
  $("#destinationRank").innerHTML = payload.destinations.length ? payload.destinations.map((item) => {
    const bytes = item.upload + item.download;
    return `<div class="rank-row"><div><strong title="${escapeHtml(item.target)}">${escapeHtml(item.target)}</strong><div class="rank-track"><i style="width:${Math.max(3, bytes / maxDestination * 100)}%"></i></div></div><small>${formatBytes(bytes)}</small></div>`;
  }).join("") : `<div class="geo-offline"><span><svg><use href="#icon-activity"/></svg></span><h3>暂无目标排行</h3><p>产生 VPN 流量后显示。</p></div>`;

  const geo = payload.geoip;
  $("#geoMessage").textContent = geo.message;
  const maxCountry = Math.max(...geo.countries.map((item) => item.bytes), 1);
  $("#countryGrid").innerHTML = geo.countries.length ? geo.countries.map((item) => `
    <div class="country-row"><span class="country-code">${escapeHtml(item.code)}</span><div><strong>${escapeHtml(item.name)}</strong><div class="rank-track"><i style="width:${Math.max(3, item.bytes / maxCountry * 100)}%"></i></div></div><small>${formatBytes(item.bytes)}</small></div>`).join("")
    : `<div class="geo-offline"><span><svg><use href="#icon-globe"/></svg></span><h3>${geo.state === "ready" ? "暂无公网目的地" : "国家数据库未就绪"}</h3><p>${escapeHtml(geo.message)}。Country.mmdb 仅提供国家/地区归属，不展示虚构城市坐标。</p></div>`;
}

async function loadTraffic() {
  try {
    const params = trafficQuery();
    const payload = await api(`/api/audit/traffic?${params}`);
    $("#trafficExport").href = `/api/audit/traffic.csv?${params}`;
    renderTraffic(payload);
    if ($("#traffic-targets").classList.contains("active")) await loadTargets();
  } catch (error) {
    showToast(error.message);
  }
}

async function loadTargets() {
  try {
    const payload = await api(`/api/audit/targets?${trafficQuery()}`);
    state.targets = payload.targets || [];
    $("#targetsTable").innerHTML = state.targets.map((item) => `<tr>
      <td><strong>${escapeHtml(item.target)}</strong></td><td class="target-cell"><strong>${item.type === "domain" ? "域名" : "IP"}</strong><small>${escapeHtml(item.ips.join(", "))}</small></td>
      <td>${item.users}</td><td>${formatBytes(item.uploadBytes)}</td><td>${formatBytes(item.downloadBytes)}</td>
      <td>${item.connections}</td><td>${formatDate(item.lastSeen)}</td></tr>`).join("");
    $("#targetCount").textContent = `${state.targets.length} 个目标`;
    $("#targetsEmpty").classList.toggle("visible", state.targets.length === 0);
  } catch (error) {
    showToast(error.message);
  }
}

function configureTrafficTimer() {
  clearInterval(state.trafficTimer);
  state.trafficTimer = null;
  if (state.view !== "traffic") return;
  const seconds = Number($("#trafficRefresh")?.value || 0);
  if (seconds) state.trafficTimer = setInterval(loadTraffic, seconds * 1000);
}

async function loadGeoSettings() {
  try {
    const payload = await api("/api/geoip");
    Object.entries(payload.settings).forEach(([key, value]) => {
      const input = $(`#geoForm [name="${key}"]`);
      if (input) input.value = value;
    });
    $("#geoError").textContent = "";
    $("#geoDialog").showModal();
  } catch (error) {
    showToast(error.message);
  }
}

async function saveGeoSettings(event) {
  event.preventDefault();
  const submitter = event.submitter;
  if (submitter?.value === "cancel") {
    $("#geoDialog").close();
    return;
  }
  const button = $("#saveGeoButton");
  const payload = Object.fromEntries(new FormData(event.currentTarget));
  payload.updateIntervalHours = Number(payload.updateIntervalHours);
  payload.retentionDays = Number(payload.retentionDays);
  button.disabled = true;
  try {
    await api("/api/geoip", { method: "PUT", body: JSON.stringify(payload) });
    $("#geoDialog").close();
    await loadTraffic();
    showToast("GeoIP 与保留策略已应用");
  } catch (error) {
    $("#geoError").textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

function renderProfiles() {
  $("#profileCount").textContent = `${state.profiles.length} 个文件`;
  $("#profilesEmpty").classList.toggle("visible", state.profiles.length === 0);
  $("#profileGrid").style.display = state.profiles.length ? "" : "none";
  $("#profileGrid").innerHTML = state.profiles.map((profile) => `
    <article class="profile-card"><span class="profile-file-icon"><svg><use href="#icon-file"/></svg></span>
      <span class="profile-meta"><strong>${escapeHtml(profile.filename)}</strong><small>${formatBytes(profile.size)} · ${formatDate(profile.updatedAt)}</small></span>
      <a class="download-button" href="/api/profiles/${encodeURIComponent(profile.filename)}/download" aria-label="下载 ${escapeHtml(profile.filename)}"><svg><use href="#icon-download"/></svg></a>
    </article>`).join("");
}

async function loadProfiles() {
  try {
    const payload = await api("/api/profiles");
    state.profiles = payload.profiles || [];
    renderProfiles();
  } catch (error) {
    showToast(error.message);
  }
}

function openProfileDialog() {
  $("#profileError").textContent = "";
  $("#profileDialog").showModal();
  requestAnimationFrame(() => $("#profileName").focus());
}

async function createProfile(event) {
  event.preventDefault();
  if (event.submitter?.value === "cancel") {
    $("#profileDialog").close();
    return;
  }
  const button = $("#createProfileButton");
  const data = Object.fromEntries(new FormData(event.currentTarget));
  $("#profileError").textContent = "";
  button.disabled = true;
  button.querySelector("span").textContent = "正在生成…";
  try {
    await api("/api/profiles", { method: "POST", body: JSON.stringify(data) });
    $("#profileDialog").close();
    event.currentTarget.reset();
    if (state.status) $("#profileHost").value = state.status.config.server.remoteHost || "";
    await loadProfiles();
    showToast(`已生成 ${data.name}.ovpn`);
  } catch (error) {
    $("#profileError").textContent = error.message;
  } finally {
    button.disabled = false;
    button.querySelector("span").textContent = "生成配置";
  }
}

async function loadCertificates() {
  try {
    const payload = await api("/api/certificates");
    $("#certificateList").innerHTML = payload.certificates.map((item) => {
      const files = Object.entries(item.files);
      return `<article class="certificate-entry">
        <span class="certificate-emblem ${item.ready ? "" : "warning"}"><svg><use href="#icon-certificate"/></svg></span>
        <div><div class="instance-title"><h2>${escapeHtml(item.name)}</h2><span class="${item.ready ? "status-badge" : "event-badge disconnect"}">${item.ready ? "材料完整" : "材料不完整"}</span></div><p>${escapeHtml(item.subject || "尚无可读取的证书主题")}</p><div class="file-dots" title="${files.map(([key, value]) => `${key}: ${value ? "存在" : "缺失"}`).join(" · ")}">${files.map(([, value]) => `<i class="${value ? "" : "missing"}"></i>`).join("")}</div></div>
        <dl><dt>分配实例</dt><dd>${item.assignedInstances}</dd></dl><dl><dt>生效时间</dt><dd>${escapeHtml(item.notBefore || "—")}</dd></dl><dl><dt>到期时间</dt><dd>${escapeHtml(item.notAfter || "—")}</dd></dl>
      </article>`;
    }).join("");
  } catch (error) {
    showToast(error.message);
  }
}

function fileToBase64(file) {
  return file.arrayBuffer().then((buffer) => {
    const bytes = new Uint8Array(buffer);
    let binary = "";
    for (let index = 0; index < bytes.length; index += 32768) {
      binary += String.fromCharCode(...bytes.subarray(index, index + 32768));
    }
    return btoa(binary);
  });
}

async function saveCertificates(event) {
  event.preventDefault();
  if (event.submitter?.value === "cancel") {
    $("#certificateDialog").close();
    return;
  }
  const button = $("#saveCertificateButton");
  const inputs = [...event.currentTarget.querySelectorAll('input[type="file"]')];
  const selected = inputs.filter((input) => input.files?.length);
  if (!selected.length) {
    $("#certificateError").textContent = "请至少选择一个证书文件";
    return;
  }
  button.disabled = true;
  try {
    const files = {};
    for (const input of selected) files[input.name] = await fileToBase64(input.files[0]);
    await api("/api/certificates/default", { method: "PUT", body: JSON.stringify({ files }) });
    $("#certificateDialog").close();
    event.currentTarget.reset();
    await loadCertificates();
    showToast("证书材料已更新；请重启 OpenVPN 容器使其生效");
  } catch (error) {
    $("#certificateError").textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

function renderMarkdown(markdown) {
  const escaped = escapeHtml(markdown).replace(/\r/g, "");
  const lines = escaped.split("\n");
  let inCode = false;
  let inList = false;
  const html = [];
  for (const line of lines) {
    if (line.startsWith("```")) {
      if (inList) { html.push("</ul>"); inList = false; }
      html.push(inCode ? "</code></pre>" : "<pre><code>");
      inCode = !inCode;
      continue;
    }
    if (inCode) { html.push(`${line}\n`); continue; }
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      if (inList) { html.push("</ul>"); inList = false; }
      const level = heading[1].length;
      const id = heading[2].toLowerCase().replace(/[^a-z0-9\u4e00-\u9fff]+/g, "-");
      html.push(`<h${level} id="${id}">${heading[2]}</h${level}>`);
    } else if (line.startsWith("- ")) {
      if (!inList) { html.push("<ul>"); inList = true; }
      html.push(`<li>${line.slice(2)}</li>`);
    } else if (line.trim()) {
      if (inList) { html.push("</ul>"); inList = false; }
      html.push(`<p>${line.replace(/`([^`]+)`/g, "<code>$1</code>")}</p>`);
    }
  }
  if (inList) html.push("</ul>");
  if (inCode) html.push("</code></pre>");
  return html.join("");
}

async function loadDocs() {
  try {
    const payload = await api("/api/docs");
    const content = $("#docsContent");
    content.classList.remove("loading-block");
    content.innerHTML = renderMarkdown(payload.content);
    const headings = [...content.querySelectorAll("h1,h2,h3")];
    $("#docsToc").innerHTML = headings.map((heading) => `<a href="#${heading.id}" style="padding-left:${9 + (Number(heading.tagName[1]) - 1) * 10}px">${escapeHtml(heading.textContent)}</a>`).join("");
  } catch (error) {
    showToast(error.message);
  }
}

function applyBranding(value) {
  state.branding = value;
  document.title = value.title || "OpenVPN 控制台";
  $(".brand strong").textContent = value.brandName || "OpenVPN";
  $(".brand small").textContent = value.productName || "OAuth2 Control";
  $("#brandPreview h2").textContent = value.title || "";
  $("#brandPreview > span:not(.brand-preview-mark)").textContent = value.description || "";
  $("#brandPreview small").textContent = value.copyright || "";
}

async function loadBranding() {
  try {
    const value = await api("/api/branding");
    applyBranding(value);
    Object.entries(value).forEach(([key, item]) => {
      const input = $(`#brandingForm [name="${key}"]`);
      if (input) input.value = item;
    });
  } catch (error) {
    showToast(error.message);
  }
}

async function saveBranding(event) {
  event.preventDefault();
  const button = $("#saveBranding");
  button.disabled = true;
  try {
    const value = await api("/api/branding", {
      method: "PUT",
      body: JSON.stringify(Object.fromEntries(new FormData(event.currentTarget))),
    });
    applyBranding(value);
    showToast("品牌设置已保存");
  } catch (error) {
    showToast(error.message);
  } finally {
    button.disabled = false;
  }
}

function settingInput(name) {
  return $(`#systemSettingsForm [name="${name}"]`);
}

function setSettingValue(name, value) {
  const input = settingInput(name);
  if (!input) return;
  if (input.type === "checkbox") input.checked = Boolean(value);
  else input.value = value ?? "";
  if (input.tagName === "SELECT") input.dispatchEvent(new Event("change", { bubbles: true }));
}

function getSettingValue(name) {
  const input = settingInput(name);
  if (!input) return "";
  if (input.type === "checkbox") return input.checked;
  if (input.type === "number") return Number(input.value);
  return input.value.trim();
}

function updateIpv6Fields() {
  const enabled = settingInput("networking.ipv6Enabled")?.checked;
  $("#ipv6Fields").classList.toggle("disabled", !enabled);
  $$("#ipv6Fields input").forEach((input) => { input.disabled = !enabled; });
}

function renderSystemSettings(payload) {
  state.settings = payload;
  const runtime = payload.runtime;
  ["server", "networking", "certificates", "oauth2"].forEach((section) => {
    Object.entries(runtime[section] || {}).forEach(([key, value]) => {
      if (Array.isArray(value)) {
        value.forEach((item, index) => setSettingValue(`${section}.${key}.${index}`, item));
      } else {
        setSettingValue(`${section}.${key}`, value);
      }
    });
  });
  setSettingValue("audit.trafficEnabled", payload.audit.trafficEnabled);
  setSettingValue("console.authEnabled", payload.console.authEnabled);
  setSettingValue("console.username", payload.console.username);
  setSettingValue("console.password", "");
  setSettingValue("secrets.clientSecret", "");
  setSettingValue("secrets.httpSecret", "");
  setSettingValue("secrets.managementPassword", "");
  $("#clientSecretState").textContent = runtime.secrets.clientSecret.configured
    ? "已配置；留空不会覆盖" : "尚未配置";
  $("#httpSecretState").textContent = runtime.secrets.httpSecret.configured
    ? "已配置；留空不会覆盖" : "尚未配置";
  $("#managementPasswordState").textContent = runtime.secrets.managementPassword.configured
    ? "已配置；留空不会覆盖" : "未单独配置，将使用首次启动默认值";
  $("#consolePasswordState").textContent = payload.console.passwordConfigured
    ? `密码已配置 · ${payload.console.source === "web" ? "网页管理" : "首次启动参数"}`
    : "尚未配置密码";
  const secretInputs = [
    settingInput("secrets.clientSecret"),
    settingInput("secrets.httpSecret"),
    settingInput("secrets.managementPassword"),
  ];
  secretInputs.forEach((input) => { input.disabled = !runtime.encryptionReady; });
  $("#encryptionNote").classList.toggle("warning", !runtime.encryptionReady);
  $("#encryptionNote span").textContent = runtime.encryptionReady
    ? "敏感字段使用环境变量中的加密主密钥加密保存，接口不会回传明文。"
    : "未设置 CONFIG_ENCRYPTION_KEY；可查看配置，但暂不能在网页保存新的 Secret。";
  $("#settingsState").innerHTML = `<svg><use href="#icon-lock"/></svg>${runtime.persisted ? "网页配置已接管" : "等待首次保存"}`;
  $("#settingsSaveTitle").textContent = "配置已同步";
  $("#settingsSaveHint").textContent = runtime.persisted
    ? `上次保存：${formatDate(new Date(runtime.updatedAt * 1000).toISOString())}`
    : "首次保存后可移除大部分 .env 项";
  $("#settingsError").textContent = "";
  updateIpv6Fields();
}

async function loadSystemSettings() {
  try {
    renderSystemSettings(await api("/api/settings"));
  } catch (error) {
    $("#settingsError").textContent = error.message;
  }
}

function systemSettingsPayload() {
  return {
    runtime: {
      server: {
        remoteHost: getSettingValue("server.remoteHost"),
        port: getSettingValue("server.port"),
        protocol: getSettingValue("server.protocol"),
        device: getSettingValue("server.device"),
        network: getSettingValue("server.network"),
        netmask: getSettingValue("server.netmask"),
        dns: getSettingValue("server.dns"),
        cipher: getSettingValue("server.cipher"),
      },
      networking: {
        outboundInterface: getSettingValue("networking.outboundInterface"),
        ipv4Nat: getSettingValue("networking.ipv4Nat"),
        ipv6Enabled: getSettingValue("networking.ipv6Enabled"),
        ipv6Network: getSettingValue("networking.ipv6Network"),
        ipv6Route: getSettingValue("networking.ipv6Route"),
        ipv6Dns: getSettingValue("networking.ipv6Dns"),
        ipv6Nat: getSettingValue("networking.ipv6Nat"),
        ipv6InternalRoutes: [0, 1, 2].map((index) => getSettingValue(`networking.ipv6InternalRoutes.${index}`)),
      },
      certificates: {
        generate: getSettingValue("certificates.generate"),
        forceRegenerate: getSettingValue("certificates.forceRegenerate"),
        generateDefaultProfile: getSettingValue("certificates.generateDefaultProfile"),
      },
      oauth2: {
        issuer: getSettingValue("oauth2.issuer"),
        clientId: getSettingValue("oauth2.clientId"),
        baseUrl: getSettingValue("oauth2.baseUrl"),
        httpListen: getSettingValue("oauth2.httpListen"),
        openvpnAddress: getSettingValue("oauth2.openvpnAddress"),
      },
      secrets: {
        clientSecret: getSettingValue("secrets.clientSecret"),
        httpSecret: getSettingValue("secrets.httpSecret"),
        managementPassword: getSettingValue("secrets.managementPassword"),
      },
    },
    audit: { trafficEnabled: getSettingValue("audit.trafficEnabled") },
    console: {
      authEnabled: getSettingValue("console.authEnabled"),
      username: getSettingValue("console.username"),
      password: getSettingValue("console.password"),
    },
  };
}

async function saveSystemSettings(event) {
  event.preventDefault();
  const button = $("#saveSystemSettings");
  button.disabled = true;
  $("#settingsError").textContent = "";
  try {
    const result = await api("/api/settings", {
      method: "PUT",
      body: JSON.stringify(systemSettingsPayload()),
    });
    renderSystemSettings(result);
    $("#settingsSaveTitle").textContent = "设置已保存";
    $("#settingsSaveHint").textContent = "审计与安全设置已应用；服务、网络和 OAuth2 参数需重启容器";
    showToast("设置已安全保存；部分参数重启容器后生效");
  } catch (error) {
    $("#settingsError").textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

function enhanceSelect(select) {
  const wrapper = document.createElement("div");
  wrapper.className = "custom-select";
  const trigger = document.createElement("button");
  trigger.type = "button";
  trigger.className = "custom-select-trigger";
  trigger.setAttribute("aria-haspopup", "listbox");
  trigger.setAttribute("aria-expanded", "false");
  trigger.setAttribute("aria-label", select.closest("label")?.querySelector(":scope > span")?.textContent || "选择");
  const menu = document.createElement("div");
  menu.className = "custom-select-menu";
  menu.setAttribute("role", "listbox");
  let activeIndex = select.selectedIndex;

  function render() {
    trigger.textContent = select.options[select.selectedIndex]?.textContent || "";
    const label = select.closest("label")?.querySelector(":scope > span")?.textContent || "选择";
    trigger.setAttribute("aria-label", `${label}：${trigger.textContent}`);
    menu.innerHTML = [...select.options].map((option, index) => `<button type="button" role="option" class="custom-select-option ${option.selected ? "selected" : ""} ${index === activeIndex ? "active" : ""}" data-index="${index}" aria-selected="${option.selected}">${escapeHtml(option.textContent)}</button>`).join("");
  }
  function close() {
    menu.classList.remove("open");
    trigger.setAttribute("aria-expanded", "false");
  }
  function open() {
    $$(".custom-select-menu.open").forEach((item) => item !== menu && item.classList.remove("open"));
    activeIndex = select.selectedIndex;
    render();
    menu.classList.add("open");
    trigger.setAttribute("aria-expanded", "true");
    const rect = trigger.getBoundingClientRect();
    const estimatedHeight = Math.min(select.options.length * 36 + 8, 260);
    const above = innerHeight - rect.bottom < estimatedHeight && rect.top > estimatedHeight;
    Object.assign(menu.style, {
      left: `${Math.max(8, Math.min(rect.left, innerWidth - Math.max(rect.width, 160) - 8))}px`,
      top: above ? `${rect.top - estimatedHeight - 4}px` : `${rect.bottom + 4}px`,
      width: `${Math.max(rect.width, 160)}px`,
      maxHeight: "260px",
      overflowY: "auto",
    });
  }
  function choose(index) {
    select.selectedIndex = index;
    select.dispatchEvent(new Event("change", { bubbles: true }));
    render();
    close();
    trigger.focus();
  }
  trigger.addEventListener("click", () => menu.classList.contains("open") ? close() : open());
  trigger.addEventListener("keydown", (event) => {
    if (["ArrowDown", "ArrowUp", "Enter", " ", "Escape"].includes(event.key)) event.preventDefault();
    if (event.key === "Escape") { close(); return; }
    if (!menu.classList.contains("open")) { open(); return; }
    if (event.key === "ArrowDown") activeIndex = Math.min(select.options.length - 1, activeIndex + 1);
    if (event.key === "ArrowUp") activeIndex = Math.max(0, activeIndex - 1);
    if (event.key === "Enter" || event.key === " ") { choose(activeIndex); return; }
    render();
  });
  menu.addEventListener("click", (event) => {
    const option = event.target.closest("[data-index]");
    if (option) choose(Number(option.dataset.index));
  });
  document.addEventListener("click", (event) => {
    if (!wrapper.contains(event.target) && !menu.contains(event.target)) close();
  });
  select.classList.add("native-select-hidden");
  select.setAttribute("aria-hidden", "true");
  select.tabIndex = -1;
  select.parentNode.insertBefore(wrapper, select);
  wrapper.append(trigger, select);
  document.body.append(menu);
  select.addEventListener("change", render);
  render();
}

$$(".nav-item").forEach((item) => item.addEventListener("click", () => showView(item.dataset.view)));
$$("[data-go]").forEach((item) => item.addEventListener("click", () => showView(item.dataset.go)));
$$("[data-open-profile]").forEach((item) => item.addEventListener("click", openProfileDialog));
$("#openProfileDialog").addEventListener("click", openProfileDialog);
$("#profileForm").addEventListener("submit", createProfile);
$("#refreshButton").addEventListener("click", () => refreshStatus(true));
$("#connectionSearch").addEventListener("input", debounce(loadConnectionAudit, 250));
$("#connectionEvent").addEventListener("change", loadConnectionAudit);
$("#connectionRange").addEventListener("change", loadConnectionAudit);
$("#trafficSearch").addEventListener("input", debounce(loadTraffic, 250));
$("#trafficRange").addEventListener("change", loadTraffic);
$("#trafficRefresh").addEventListener("change", configureTrafficTimer);
$$("[data-traffic-tab]").forEach((button) => button.addEventListener("click", () => {
  $$("[data-traffic-tab]").forEach((item) => item.classList.toggle("active", item === button));
  $$(".traffic-tab").forEach((tab) => tab.classList.toggle("active", tab.id === `traffic-${button.dataset.trafficTab}`));
  if (button.dataset.trafficTab === "targets") loadTargets();
}));
$("#openGeoDialog").addEventListener("click", loadGeoSettings);
$("#geoForm").addEventListener("submit", saveGeoSettings);
$("#brandingForm").addEventListener("submit", saveBranding);
$("#systemSettingsForm").addEventListener("submit", saveSystemSettings);
$("#systemSettingsForm").addEventListener("input", () => {
  $("#settingsSaveTitle").textContent = "存在尚未保存的修改";
  $("#settingsSaveHint").textContent = "检查后保存，页面会提示具体生效方式";
});
$("#ipv6Enabled").addEventListener("change", updateIpv6Fields);
$("#openCertificateDialog").addEventListener("click", () => {
  $("#certificateError").textContent = "";
  $("#certificateDialog").showModal();
});
$("#certificateForm").addEventListener("submit", saveCertificates);
$$("select").forEach(enhanceSelect);
$("#menuButton").addEventListener("click", () => { $("#sidebar").classList.add("open"); $("#sidebarBackdrop").classList.add("visible"); });
$("#sidebarBackdrop").addEventListener("click", () => { $("#sidebar").classList.remove("open"); $("#sidebarBackdrop").classList.remove("visible"); });
$("#profileDialog").addEventListener("click", (event) => { if (event.target === event.currentTarget) event.currentTarget.close(); });

function debounce(callback, delay) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => callback(...args), delay);
  };
}

const initialView = location.hash.slice(1);
const views = ["overview", "instance", "connections", "traffic", "certificates", "profiles", "docs", "settings", "branding"];
if (views.includes(initialView)) showView(initialView);
refreshStatus();
loadProfiles();
loadBranding();
setInterval(refreshStatus, 10_000);
