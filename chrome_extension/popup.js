// popup.js - CIDM Universal Download & Stream Detection Popup
const BRIDGE = "http://127.0.0.1:9632";
const statusEl = document.getElementById("status");
const toggle = document.getElementById("toggle");
const quickUrlInput = document.getElementById("quick-url");
const quickBtn = document.getElementById("quick-btn");
const downloadTabBtn = document.getElementById("download-tab-btn");
const streamsListEl = document.getElementById("streams-list");
const streamCountEl = document.getElementById("stream-count");
const msgEl = document.getElementById("msg");

// Cross-browser session storage wrapper
const sessionStore = (typeof chrome !== "undefined" && chrome.storage && chrome.storage.session) ? chrome.storage.session : {
  get: async (keys) => {
    try {
      if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
        return (await chrome.storage.local.get(keys)) || {};
      }
      return {};
    } catch (_e) { return {}; }
  },
};

let activeTabId = null;
let lastSignature = "";

function setStatus(online) {
  statusEl.textContent = online ? "Connected" : "Offline";
  statusEl.className = "badge " + (online ? "on" : "off");
  if (quickBtn) quickBtn.disabled = !online;
}

async function checkConnection() {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 1500);
  try {
    const res = await fetch(`${BRIDGE}/ping`, { signal: controller.signal, cache: "no-store" });
    const data = await res.json();
    setStatus(res.ok && data.status === "ok");
  } catch (_err) {
    setStatus(false);
  } finally {
    clearTimeout(timer);
  }
}

function renderStreams(list, subtitles) {
  const signature = JSON.stringify({
    streams: (list || []).map((m) => m.url),
    subs: (subtitles || []).map((s) => s.url),
  });
  if (signature === lastSignature) return;
  lastSignature = signature;
  streamsListEl.textContent = "";

  const count = (list || []).length;
  if (streamCountEl) {
    streamCountEl.textContent = String(count);
  }

  if (!list || !list.length) {
    const p = document.createElement("div");
    p.className = "empty";
    p.textContent = "No active video streams detected. Standard file downloads (ZIP, EXE, ISO, PDF, etc.) are intercepted automatically.";
    streamsListEl.appendChild(p);
    return;
  }

  const subCount = (subtitles || []).length;

  for (const stream of [...list].reverse()) {
    const row = document.createElement("div");
    row.className = "item";

    const tag = document.createElement("span");
    const stType = (stream.stream_type || "mp4").toLowerCase();
    tag.className = `tag ${stType}`;
    tag.textContent = stType.toUpperCase();

    const meta = document.createElement("div");
    meta.className = "meta";

    const name = document.createElement("div");
    name.className = "name";
    name.textContent = stream.filename || "Video Stream";
    name.title = stream.url;

    const hint = document.createElement("div");
    hint.className = "hint-text";
    let hostHint = stream.host;
    if (!hostHint) {
      try { hostHint = new URL(stream.url).hostname; } catch (_e) { hostHint = ""; }
    }
    const subHint = subCount > 0 ? ` • ${subCount} Subtitle(s)` : "";
    hint.textContent = (hostHint ? `${hostHint} - ${stType.toUpperCase()}` : stType.toUpperCase()) + subHint;

    meta.append(name, hint);

    const btn = document.createElement("button");
    btn.className = "dl-btn";
    btn.textContent = "Download";
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      msgEl.textContent = "";
      try {
        const res = await chrome.runtime.sendMessage({
          type: "downloadStream",
          stream,
          tabId: activeTabId,
        });
        if (res && res.ok) {
          btn.textContent = "Sent";
          btn.classList.add("sent");
        } else {
          btn.disabled = false;
          msgEl.textContent = (res && res.error) || "Could not reach the desktop app.";
        }
      } catch (err) {
        btn.disabled = false;
        msgEl.textContent = String(err.message || err);
      }
    });

    row.append(tag, meta, btn);
    streamsListEl.appendChild(row);
  }
}

async function loadStreams() {
  if (activeTabId === null) return;
  try {
    const res = await chrome.runtime.sendMessage({ type: "getDetectedStreams", tabId: activeTabId });
    if (res && res.ok) {
      renderStreams(res.streams || [], res.subtitles || []);
    } else {
      const storedStreams = await sessionStore.get(`streams:${activeTabId}`);
      const storedSubs = await sessionStore.get(`subtitles:${activeTabId}`);
      renderStreams(storedStreams[`streams:${activeTabId}`] || [], storedSubs[`subtitles:${activeTabId}`] || []);
    }
  } catch (_e) {
    try {
      const storedStreams = await sessionStore.get(`streams:${activeTabId}`);
      const storedSubs = await sessionStore.get(`subtitles:${activeTabId}`);
      renderStreams(storedStreams[`streams:${activeTabId}`] || [], storedSubs[`subtitles:${activeTabId}`] || []);
    } catch (_err) {}
  }
}

async function triggerQuickDownload() {
  if (!quickUrlInput) return;
  const url = quickUrlInput.value.trim();
  if (!url) {
    msgEl.textContent = "Please enter or paste a valid download URL.";
    return;
  }
  if (!/^https?:\/\//i.test(url)) {
    msgEl.textContent = "URL must start with http:// or https://";
    return;
  }

  msgEl.textContent = "";
  quickBtn.disabled = true;
  const origText = quickBtn.textContent;
  quickBtn.textContent = "Sending...";

  try {
    const res = await chrome.runtime.sendMessage({
      type: "quickDownload",
      url,
    });
    if (res && res.ok) {
      quickBtn.textContent = "Sent!";
      quickUrlInput.value = "";
      setTimeout(() => {
        quickBtn.textContent = origText;
        quickBtn.disabled = false;
      }, 1800);
    } else {
      throw new Error((res && res.error) || "Failed to send download to CIDM.");
    }
  } catch (err) {
    msgEl.textContent = String(err.message || err);
    quickBtn.textContent = origText;
    quickBtn.disabled = false;
  }
}

if (quickBtn) {
  quickBtn.addEventListener("click", triggerQuickDownload);
}

if (quickUrlInput) {
  quickUrlInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      triggerQuickDownload();
    }
  });
}

if (downloadTabBtn) {
  downloadTabBtn.addEventListener("click", async () => {
    msgEl.textContent = "";
    downloadTabBtn.disabled = true;
    try {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (!tab || !tab.id || !tab.url || !/^https?:\/\//i.test(tab.url)) {
        throw new Error("No active web page URL to download.");
      }
      const res = await chrome.runtime.sendMessage({ type: "downloadCurrentTab", tabId: tab.id });
      if (res && res.ok) {
        const origText = downloadTabBtn.innerHTML;
        downloadTabBtn.textContent = "Sent to CIDM!";
        downloadTabBtn.classList.add("success");
        setTimeout(() => {
          downloadTabBtn.innerHTML = origText;
          downloadTabBtn.classList.remove("success");
          downloadTabBtn.disabled = false;
        }, 2000);
      } else {
        throw new Error((res && res.error) || "Could not reach the CIDM desktop app.");
      }
    } catch (err) {
      msgEl.textContent = String(err.message || err);
      downloadTabBtn.disabled = false;
    }
  });
}

async function init() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  activeTabId = tab ? tab.id : null;
  loadStreams();
  setInterval(loadStreams, 1500);

  const { interceptEnabled } = await chrome.storage.local.get("interceptEnabled");
  toggle.checked = interceptEnabled !== false;
  toggle.addEventListener("change", () => {
    chrome.storage.local.set({ interceptEnabled: toggle.checked });
  });

  checkConnection();
  setInterval(checkConnection, 3000);
}

init();
