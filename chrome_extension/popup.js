// popup.js - CIDM Stream & Subtitle Detection Popup
const BRIDGE = "http://127.0.0.1:9632";
const statusEl = document.getElementById("status");
const toggle = document.getElementById("toggle");
const downloadTabBtn = document.getElementById("download-tab-btn");
const streamsListEl = document.getElementById("streams-list");
const msgEl = document.getElementById("msg");

let activeTabId = null;
let lastSignature = "";

function setStatus(online) {
  statusEl.textContent = online ? "Desktop App Connected" : "Desktop App Offline";
  statusEl.className = "badge " + (online ? "on" : "off");
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

  if (!list || !list.length) {
    const p = document.createElement("div");
    p.className = "empty";
    p.textContent = "No video streams detected yet. Start playing a video on this page or click 'Download Current Tab' above.";
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
    const subHint = subCount > 0 ? ` • ${subCount} Subtitle(s) Detected` : "";
    hint.textContent = (hostHint ? `${hostHint} - ${stType.toUpperCase()} Stream` : `${stType.toUpperCase()} Stream`) + subHint;

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
      const storedStreams = await chrome.storage.session.get(`streams:${activeTabId}`);
      const storedSubs = await chrome.storage.session.get(`subtitles:${activeTabId}`);
      renderStreams(storedStreams[`streams:${activeTabId}`] || [], storedSubs[`subtitles:${activeTabId}`] || []);
    }
  } catch (_e) {
    try {
      const storedStreams = await chrome.storage.session.get(`streams:${activeTabId}`);
      const storedSubs = await chrome.storage.session.get(`subtitles:${activeTabId}`);
      renderStreams(storedStreams[`streams:${activeTabId}`] || [], storedSubs[`subtitles:${activeTabId}`] || []);
    } catch (_err) {}
  }
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
