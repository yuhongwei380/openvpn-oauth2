const form = document.querySelector("#loginForm");
const error = document.querySelector("#loginError");
const button = document.querySelector("#loginButton");
const password = document.querySelector("#password");
const toggle = document.querySelector("#togglePassword");

function destination() {
  const value = new URLSearchParams(location.search).get("next") || "/";
  return value.startsWith("/") && !value.startsWith("//") ? value : "/";
}

async function checkSession() {
  try {
    const response = await fetch("/api/auth/session", { credentials: "same-origin" });
    const payload = await response.json();
    if (payload.authenticated) location.replace(destination());
  } catch {
    error.textContent = "暂时无法连接管理服务，请稍后重试。";
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  error.textContent = "";
  button.disabled = true;
  button.querySelector("span").textContent = "正在验证";
  try {
    const response = await fetch("/api/auth/login", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.fromEntries(new FormData(form))),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || "登录失败，请稍后重试");
    location.replace(destination());
  } catch (requestError) {
    error.textContent = requestError.message;
    password.select();
  } finally {
    button.disabled = false;
    button.querySelector("span").textContent = "进入控制台";
  }
});

toggle.addEventListener("click", () => {
  const visible = password.type === "text";
  password.type = visible ? "password" : "text";
  toggle.textContent = visible ? "显示" : "隐藏";
  toggle.setAttribute("aria-label", visible ? "显示密码" : "隐藏密码");
  password.focus();
});

checkSession();
