// background.js - CIDM Universal Web Stream & Subtitle Sniffer & Desktop Bridge
const BRIDGE = "http://127.0.0.1:9632";
const handledIds = new Set();
const bypassUrls = new Set();

// In-memory per-tab stream & subtitle registries; persisted to chrome.storage.session
const detectedStreamsByTab = new Map();
const detectedSubtitlesByTab = new Map();
const MAX_PER_TAB = 30;

// Initialize session state on worker startup
chrome.storage.session.get(null).then((items) => {
  if (items) {
    for (const [k, v] of Object.entries(items)) {
      if (k.startsWith("streams:") && Array.isArray(v)) {
        const tabId = parseInt(k.split(":")[1], 10);
        if (!isNaN(tabId)) {
          detectedStreamsByTab.set(tabId, v);
        }
      } else if (k.startsWith("subtitles:") && Array.isArray(v)) {
        const tabId = parseInt(k.split(":")[1], 10);
        if (!isNaN(tabId)) {
          detectedSubtitlesByTab.set(tabId, v);
        }
      }
    }
  }
}).catch((e) => console.warn("Failed to restore session state:", e));

chrome.runtime.onInstalled.addListener(async () => {
  const { interceptEnabled } = await chrome.storage.local.get("interceptEnabled");
  if (interceptEnabled === undefined) {
    await chrome.storage.local.set({ interceptEnabled: true });
  }

  // Register context menu for all web links, media, and pages
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: "cidm-download-context",
      title: "Download with CIDM",
      contexts: ["page", "link", "video", "audio", "image"],
    });
    chrome.contextMenus.create({
      id: "cidm-download-all-links",
      title: "Download all links with CIDM",
      contexts: ["page", "selection"],
    });
  });
});

async function isDesktopAppRunning() {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 1500);
  try {
    const res = await fetch(`${BRIDGE}/ping`, { signal: controller.signal, cache: "no-store" });
    if (!res.ok) return false;
    const data = await res.json();
    return data && data.status === "ok";
  } catch (_err) {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

function cookieHeader(cookies) {
  return (cookies || []).map((c) => `${c.name}=${c.value}`).join("; ");
}

function safeName(title) {
  return (title || "").replace(/[\\/:*?"<>|\u0000-\u001f]+/g, " ").replace(/\s+/g, " ").trim().slice(0, 120);
}

function isGenericFilename(name) {
  if (!name) return true;
  const s = String(name).trim().toLowerCase();
  const base = s.split(".")[0];
  const ext = s.includes(".") ? s.split(".").pop() : "";
  if (["download", "file", "view", "uc", "open", "index", "export", "stream", "get", "media"].includes(base)) {
    return true;
  }
  if (!ext) return true;
  return false;
}

function extractGoogleDriveTitle(title) {
  if (!title) return "";
  const cleaned = title.replace(/\s*-\s*Google\s+(Drive|Docs|Sheets|Slides)\s*$/i, "").trim();
  return safeName(cleaned);
}

function normalizeDownloadUrl(url) {
  if (!url || !/^https?:\/\//i.test(url)) return url;
  const m1 = url.match(/drive\.google\.com\/file\/d\/([a-zA-Z0-9_-]+)/i);
  const m2 = !m1 && url.match(/drive\.google\.com\/open\?.*?id=([a-zA-Z0-9_-]+)/i);
  const m3 = !m1 && !m2 && url.match(/drive\.google\.com\/uc\?.*?id=([a-zA-Z0-9_-]+)/i);
  const m4 = !m1 && !m2 && !m3 && url.match(/drive\.usercontent\.google\.com\/download\?.*?id=([a-zA-Z0-9_-]+)/i);
  const match = m1 || m2 || m3 || m4;
  if (match) {
    return `https://drive.usercontent.google.com/download?id=${match[1]}&export=download&confirm=t`;
  }
  if (url.includes("dropbox.com/") && url.includes("dl=0")) {
    return url.replace("dl=0", "dl=1");
  }
  return url;
}

async function sendToDesktop(payload) {
  if (payload && payload.url) {
    payload.url = normalizeDownloadUrl(payload.url);
  }
  const res = await fetch(`${BRIDGE}/add-download`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`Desktop app returned HTTP ${res.status}`);
}

// ---------------------------------------------------------------------------
// Network Sniffer: Inspect request headers to capture master manifests & streams
// ---------------------------------------------------------------------------
function isSubtitleUrl(rawUrl) {
  if (!rawUrl || !/^https?:\/\//i.test(rawUrl)) return false;
  const cleanUrl = rawUrl.split("#")[0];
  const path = cleanUrl.split("?")[0].toLowerCase();
  return path.endsWith(".vtt") || path.endsWith(".srt") || /\.(vtt|srt)(?:$|[?#])/i.test(cleanUrl);
}

function parseSubtitleLabel(url) {
  try {
    const u = new URL(url);
    const p = u.pathname.split("/").filter(Boolean).pop() || "subtitles";
    const baseName = decodeURIComponent(p.split("?")[0]);
    const langParam = u.searchParams.get("lang") || u.searchParams.get("srclang") || u.searchParams.get("label") || u.searchParams.get("language");
    if (langParam) {
      return `${baseName} (${langParam})`;
    }
    return baseName;
  } catch (_e) {
    return "Subtitles";
  }
}

function getSubtitlesForTab(tabId, frameId = null) {
  if (tabId === null || tabId === undefined || tabId < 0) return [];
  const allSubs = detectedSubtitlesByTab.get(tabId) || [];
  if (allSubs.length === 0) return [];
  if (frameId === null || frameId === undefined) return [...allSubs];

  // Prioritize subtitles captured from the matching frameId, then any other subtitles on that tab
  const matchingFrame = [];
  const otherFrames = [];
  for (const s of allSubs) {
    if (s.frameId === frameId) {
      matchingFrame.push(s);
    } else {
      otherFrames.push(s);
    }
  }
  return [...matchingFrame, ...otherFrames];
}

function classifyStreamUrl(rawUrl) {
  if (!rawUrl || !/^https?:\/\//i.test(rawUrl)) return null;
  const cleanUrl = rawUrl.split("#")[0];
  const path = cleanUrl.split("?")[0].toLowerCase();

  // Exclude tiny video/audio segment chunks, subtitles, or encryption keys
  if (/\.(ts|m4s|m4f|cmfv|cmfa|vtt|srt|key)(?:$|[?#])/i.test(cleanUrl)) {
    return null;
  }

  // HLS Master & Media Playlists
  if (/\.(m3u8|m3u)($|[?#])/i.test(cleanUrl) || path.endsWith(".m3u8") || path.endsWith(".m3u")) {
    return "hls";
  }
  // DASH Manifests
  if (/\.mpd($|[?#])/i.test(cleanUrl) || path.endsWith(".mpd")) {
    return "dash";
  }
  // Direct MP4 / WEBM streams
  if (/\.mp4($|[?#])/i.test(cleanUrl) || path.endsWith(".mp4") || path.endsWith(".m4v")) {
    return "mp4";
  }
  if (/\.webm($|[?#])/i.test(cleanUrl) || path.endsWith(".webm")) {
    return "webm";
  }
  return null;
}

function defaultFilename(url, streamType) {
  try {
    const u = new URL(url);
    const p = u.pathname.split("/").filter(Boolean).pop() || "";
    let name = decodeURIComponent(p.split("?")[0]);
    if (!name) name = "file";
    if (streamType === "hls" && (name.endsWith(".m3u8") || name.endsWith(".m3u"))) {
      return name.replace(/\.(m3u8|m3u)$/i, ".mp4");
    }
    if (streamType === "dash" && name.endsWith(".mpd")) {
      return name.replace(/\.mpd$/i, ".mp4");
    }
    return name;
  } catch (_e) {
    if (streamType === "hls" || streamType === "dash") return "stream.mp4";
    return streamType ? `file.${streamType}` : "file";
  }
}

async function updateBadge(tabId) {
  if (tabId === null || tabId === undefined || tabId < 0) return;
  const list = detectedStreamsByTab.get(tabId) || [];
  let count = list.length;
  if (count === 0) {
    try {
      const tab = await chrome.tabs.get(tabId);
      if (tab && tab.url && (tab.url.includes("youtube.com/watch") || tab.url.includes("youtu.be/") || tab.url.includes("youtube.com/shorts/"))) {
        count = 1;
      }
    } catch (_e) {}
  }
  const text = count > 0 ? String(count) : "";
  chrome.action.setBadgeBackgroundColor({ tabId, color: "#3b82f6" });
  chrome.action.setBadgeText({ tabId, text });
}

// Sniff requests with extraHeaders to capture Referer, Origin, Cookie, streams and subtitles
chrome.webRequest.onBeforeSendHeaders.addListener(
  async (details) => {
    const tabId = details.tabId;
    if (tabId < 0) return;
    if (details.url.startsWith("http://127.0.0.1:9632")) return;

    let referer = "";
    let origin = "";
    let userAgent = navigator.userAgent;
    let cookie = "";

    if (details.requestHeaders) {
      for (const h of details.requestHeaders) {
        const name = (h.name || "").toLowerCase();
        if (name === "referer") referer = h.value || "";
        else if (name === "origin") origin = h.value || "";
        else if (name === "user-agent") userAgent = h.value || userAgent;
        else if (name === "cookie") cookie = h.value || "";
      }
    }

    if (!cookie) {
      try {
        const cookies = await chrome.cookies.getAll({ url: details.url });
        cookie = cookieHeader(cookies);
      } catch (_e) {}
    }

    // 1. Sniff Subtitles (.vtt / .srt)
    if (isSubtitleUrl(details.url)) {
      const subList = detectedSubtitlesByTab.get(tabId) || [];
      if (!subList.some((s) => s.url === details.url)) {
        subList.push({
          url: details.url,
          frameId: details.frameId,
          label: parseSubtitleLabel(details.url),
          referer,
          origin,
          user_agent: userAgent,
          cookies: cookie,
          time: Date.now(),
        });
        while (subList.length > MAX_PER_TAB) subList.shift();
        detectedSubtitlesByTab.set(tabId, subList);
        chrome.storage.session.set({ [`subtitles:${tabId}`]: subList }).catch(() => {});
      }
      return;
    }

    // 2. Sniff Media Streams
    const streamType = classifyStreamUrl(details.url);
    if (!streamType) return;

    const list = detectedStreamsByTab.get(tabId) || [];

    // Ignore segmented mp4/webm chunks if XHR and tab already has an HLS or DASH manifest
    if ((streamType === "mp4" || streamType === "webm") && details.type === "xmlhttprequest") {
      const hasManifest = list.some((s) => s.stream_type === "hls" || s.stream_type === "dash");
      if (hasManifest) return;
    }

    if (list.some((s) => s.url === details.url)) {
      return;
    }

    let tabTitle = "";
    try {
      const tab = await chrome.tabs.get(tabId);
      tabTitle = tab ? tab.title : "";
    } catch (_e) {}

    let host = "";
    try {
      host = new URL(details.url).hostname;
    } catch (_e) {}

    const item = {
      url: details.url,
      tabId: details.tabId,
      frameId: details.frameId,
      referer,
      origin,
      user_agent: userAgent,
      cookies: cookie,
      stream_type: streamType,
      time: Date.now(),
      filename: safeName(tabTitle) || defaultFilename(details.url, streamType),
      host: host,
    };

    list.push(item);
    while (list.length > MAX_PER_TAB) {
      // Remove oldest non-manifest (mp4/webm) entry first so hls/dash master playlists are never evicted
      const nonManifestIdx = list.findIndex((s) => s.stream_type !== "hls" && s.stream_type !== "dash");
      if (nonManifestIdx !== -1) {
        list.splice(nonManifestIdx, 1);
      } else {
        list.shift();
      }
    }
    detectedStreamsByTab.set(tabId, list);

    try {
      await chrome.storage.session.set({ [`streams:${tabId}`]: list });
    } catch (e) {
      console.warn("Storage session write error:", e);
    }

    updateBadge(tabId);
  },
  { urls: ["<all_urls>"] },
  ["requestHeaders", "extraHeaders"]
);

// Clear a tab's stored streams & subtitles on navigation or tab close
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === "loading" && changeInfo.url) {
    detectedStreamsByTab.delete(tabId);
    detectedSubtitlesByTab.delete(tabId);
    chrome.storage.session.remove([`streams:${tabId}`, `subtitles:${tabId}`]);
    chrome.action.setBadgeText({ tabId, text: "" });
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  detectedStreamsByTab.delete(tabId);
  detectedSubtitlesByTab.delete(tabId);
  chrome.storage.session.remove([`streams:${tabId}`, `subtitles:${tabId}`]);
});

chrome.tabs.onActivated.addListener(({ tabId }) => {
  updateBadge(tabId);
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === "complete" || changeInfo.url) {
    updateBadge(tabId);
  }
});

// ---------------------------------------------------------------------------
// Standard Browser Downloads Interception (All File Types: ZIP, EXE, ISO, PDF, etc.)
// ---------------------------------------------------------------------------
async function handleBrowserDownloadItem(item, suggest) {
  try {
    if (handledIds.has(item.id)) {
      if (suggest) suggest();
      return;
    }

    const { interceptEnabled } = await chrome.storage.local.get("interceptEnabled");
    if (interceptEnabled === false) {
      if (suggest) suggest();
      return;
    }

    const url = item.finalUrl || item.url;
    if (!url || !/^https?:\/\//i.test(url)) {
      if (suggest) suggest();
      return;
    }
    if (bypassUrls.delete(item.url) || bypassUrls.delete(url)) {
      if (suggest) suggest();
      return;
    }

    const running = await isDesktopAppRunning();
    if (!running) {
      if (suggest) suggest();
      return;
    }

    handledIds.add(item.id);

    try { await chrome.downloads.cancel(item.id); } catch (_e) {}
    try { await chrome.downloads.erase({ id: item.id }); } catch (_e) {}

    let cookies = "";
    try {
      cookies = cookieHeader(await chrome.cookies.getAll({ url }));
    } catch (_e) {}

    let cleanFilename = "";
    if (item.filename) {
      cleanFilename = item.filename.split(/[/\\]/).pop();
    }
    if (isGenericFilename(cleanFilename)) {
      try {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (tab && tab.title) {
          const gdriveTitle = extractGoogleDriveTitle(tab.title);
          if (gdriveTitle && !isGenericFilename(gdriveTitle)) {
            cleanFilename = gdriveTitle;
          }
        }
      } catch (_e) {}
    }
    if (isGenericFilename(cleanFilename)) {
      cleanFilename = "";
    }

    const payload = {
      url,
      filename: cleanFilename,
      cookies,
      user_agent: navigator.userAgent,
      referer: item.referrer || "",
      origin: "",
      stream_type: "",
      file_size: item.fileSize || item.totalBytes || 0,
      mime: item.mime || "",
    };

    await sendToDesktop(payload);
  } catch (err) {
    console.warn("Download interception error:", err);
    if (suggest) {
      try { suggest(); } catch (_e) {}
    }
  }
}

// onDeterminingFilename provides the real resolved filename and headers
if (chrome.downloads && chrome.downloads.onDeterminingFilename) {
  chrome.downloads.onDeterminingFilename.addListener((item, suggest) => {
    handleBrowserDownloadItem(item, suggest);
    return true; // Keep async suggest channel open
  });
}

// Fallback for browsers or events where onDeterminingFilename is unavailable
if (chrome.downloads && chrome.downloads.onCreated) {
  chrome.downloads.onCreated.addListener((item) => {
    if (!chrome.downloads.onDeterminingFilename) {
      handleBrowserDownloadItem(item, null);
    }
  });
}

// ---------------------------------------------------------------------------
// Context Menu: "Download with CIDM" & "Download all links with CIDM"
// ---------------------------------------------------------------------------
chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === "cidm-download-all-links" || info.menuItemId === "pyidm-download-all-links") {
    if (!tab || !tab.id) return;
    if (!(await isDesktopAppRunning())) {
      chrome.action.setBadgeText({ text: "ERR" });
      chrome.action.setBadgeBackgroundColor({ color: "#ef4444" });
      setTimeout(() => updateBadge(tab.id), 3000);
      return;
    }

    try {
      const results = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: () => {
          const urls = new Set();
          const sel = window.getSelection();
          if (sel && sel.rangeCount > 0 && !sel.isCollapsed) {
            const container = document.createElement("div");
            for (let i = 0; i < sel.rangeCount; i++) {
              container.appendChild(sel.getRangeAt(i).cloneContents());
            }
            container.querySelectorAll("a[href]").forEach((a) => {
              if (/^https?:\/\//i.test(a.href)) urls.add(a.href);
            });
            const text = sel.toString();
            const textUrls = text.match(/https?:\/\/[^\s"'<>]+/gi) || [];
            textUrls.forEach((u) => urls.add(u));
          }
          if (urls.size === 0) {
            document.querySelectorAll("a[href]").forEach((a) => {
              if (/^https?:\/\//i.test(a.href)) urls.add(a.href);
            });
          }
          return Array.from(urls);
        },
      });

      const extractedUrls = (results && results[0] && results[0].result) || [];
      if (!extractedUrls.length) return;

      let cookies = "";
      try {
        cookies = cookieHeader(await chrome.cookies.getAll({ url: tab.url }));
      } catch (_e) {}

      await fetch(`${BRIDGE}/add-batch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          urls: extractedUrls,
          referer: tab.url || "",
          cookies,
          user_agent: navigator.userAgent,
          page_title: tab.title || "",
        }),
      });
    } catch (err) {
      console.warn("Failed to extract and send batch links:", err);
    }
    return;
  }

  if (info.menuItemId !== "cidm-download-context" && info.menuItemId !== "pyidm-download-context") return;

  const targetUrl = info.linkUrl || info.srcUrl || info.pageUrl;
  if (!targetUrl || !/^https?:\/\//i.test(targetUrl)) return;

  if (!(await isDesktopAppRunning())) {
    chrome.action.setBadgeText({ text: "ERR" });
    chrome.action.setBadgeBackgroundColor({ color: "#ef4444" });
    setTimeout(() => updateBadge(tab ? tab.id : -1), 3000);
    return;
  }

  let cookies = "";
  try {
    cookies = cookieHeader(await chrome.cookies.getAll({ url: targetUrl }));
  } catch (_e) {}

  let origin = "";
  try {
    origin = new URL(targetUrl).origin;
  } catch (_e) {}

  const subtitles = tab ? getSubtitlesForTab(tab.id, info.frameId) : [];

  // Determine true target filename: prefer link/media pathname before page title
  let filename = "";
  if (info.linkUrl || info.srcUrl) {
    const rawTarget = info.linkUrl || info.srcUrl;
    filename = defaultFilename(rawTarget, classifyStreamUrl(rawTarget));
  }
  if ((!filename || isGenericFilename(filename)) && tab && tab.title) {
    filename = extractGoogleDriveTitle(tab.title) || safeName(tab.title);
  }
  if (!filename) {
    filename = defaultFilename(targetUrl, classifyStreamUrl(targetUrl));
  }
  if (isGenericFilename(filename)) {
    filename = "";
  }

  const payload = {
    url: targetUrl,
    filename,
    cookies,
    user_agent: navigator.userAgent,
    referer: (tab && tab.url) || "",
    origin,
    stream_type: classifyStreamUrl(targetUrl) || "",
    subtitles,
  };

  try {
    await sendToDesktop(payload);
  } catch (err) {
    console.warn("Failed to send context menu download:", err);
  }
});

// ---------------------------------------------------------------------------
// Runtime Messages from Popup and In-Page Overlay Pill
// ---------------------------------------------------------------------------
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg) return false;

  // Retrieve detected streams for popup
  if (msg.type === "getDetectedStreams") {
    (async () => {
      const tabId = msg.tabId;
      let list = detectedStreamsByTab.get(tabId);
      if (!list) {
        const stored = await chrome.storage.session.get(`streams:${tabId}`);
        list = stored[`streams:${tabId}`] || [];
        detectedStreamsByTab.set(tabId, list);
      }
      if (list.length === 0 && tabId) {
        try {
          const tab = await chrome.tabs.get(tabId);
          if (tab && tab.url && (tab.url.includes("youtube.com/watch") || tab.url.includes("youtu.be/") || tab.url.includes("youtube.com/shorts/"))) {
            list = [{
              url: tab.url,
              streamType: "media",
              filename: safeName(tab.title) ? `${safeName(tab.title)}.mp4` : "youtube_video.mp4",
              tabTitle: tab.title || "YouTube Video",
              time: Date.now(),
              isYouTube: true,
            }];
          }
        } catch (_e) {}
      }
      const subs = detectedSubtitlesByTab.get(tabId) || [];
      sendResponse({ ok: true, streams: list, subtitles: subs });
    })();
    return true;
  }

  // Retrieve detected subtitles for popup
  if (msg.type === "getDetectedSubtitles") {
    (async () => {
      const tabId = msg.tabId;
      let list = detectedSubtitlesByTab.get(tabId);
      if (!list) {
        const stored = await chrome.storage.session.get(`subtitles:${tabId}`);
        list = stored[`subtitles:${tabId}`] || [];
        detectedSubtitlesByTab.set(tabId, list);
      }
      sendResponse({ ok: true, subtitles: list });
    })();
    return true;
  }

  // Send sniffed stream to CIDM from popup
  if (msg.type === "downloadStream" || msg.type === "downloadMedia") {
    (async () => {
      try {
        if (!(await isDesktopAppRunning())) throw new Error("CIDM desktop app is offline");
        const s = msg.stream || msg.media;
        if (!s || !s.url) throw new Error("No stream URL provided");

        const tabId = msg.tabId || (s && s.tabId);
        const frameId = s && s.frameId !== undefined ? s.frameId : null;
        const subtitles = getSubtitlesForTab(tabId, frameId);

        let cookies = s.cookies || "";
        if (!cookies && s.url) {
          try {
            cookies = cookieHeader(await chrome.cookies.getAll({ url: s.url }));
          } catch (_e) {}
        }
        let origin = s.origin || "";
        if (!origin && s.url) {
          try { origin = new URL(s.url).origin; } catch (_e) {}
        }

        await sendToDesktop({
          url: s.url,
          filename: s.filename || "",
          cookies,
          user_agent: s.user_agent || navigator.userAgent,
          referer: s.referer || s.url || "",
          origin,
          stream_type: s.stream_type || (s.kind === "hls" ? "hls" : ""),
          subtitles,
        });
        sendResponse({ ok: true });
      } catch (err) {
        sendResponse({ ok: false, error: String(err.message || err) });
      }
    })();
    return true;
  }

  // Active tab direct download
  if (msg.type === "downloadCurrentTab") {
    (async () => {
      try {
        if (!(await isDesktopAppRunning())) throw new Error("CIDM desktop app is offline");
        const tab = await chrome.tabs.get(msg.tabId);
        if (!tab || !tab.url) throw new Error("No active tab URL found");

        let cookies = "";
        try { cookies = cookieHeader(await chrome.cookies.getAll({ url: tab.url })); } catch (_e) {}

        let origin = "";
        try { origin = new URL(tab.url).origin; } catch (_e) {}

        const subtitles = getSubtitlesForTab(msg.tabId);

        await sendToDesktop({
          url: tab.url,
          filename: safeName(tab.title) || "",
          cookies,
          user_agent: navigator.userAgent,
          referer: tab.url || "",
          origin,
          stream_type: "",
          subtitles,
        });
        sendResponse({ ok: true });
      } catch (err) {
        sendResponse({ ok: false, error: String(err.message || err) });
      }
    })();
    return true;
  }

  // In-page video overlay pill download handler
  if (msg.type === "CIDM_DOWNLOAD_FRAME_VIDEO" || msg.type === "PYIDM_DOWNLOAD_FRAME_VIDEO") {
    (async () => {
      try {
        if (!(await isDesktopAppRunning())) {
          sendResponse({ ok: false, error: "OFFLINE" });
          return;
        }

        const tab = sender.tab || null;
        const tabUrl = (tab && tab.url) || "";
        const frameUrl = msg.frameUrl || "";
        const senderFrameId = sender.frameId !== undefined ? sender.frameId : 0;
        const tabId = tab ? tab.id : null;
        const subtitles = getSubtitlesForTab(tabId, senderFrameId);

        const isYouTube =
          tabUrl.includes("youtube.com") ||
          tabUrl.includes("youtu.be") ||
          frameUrl.includes("youtube.com") ||
          frameUrl.includes("youtu.be");

        if (isYouTube) {
          const targetUrl = (tabUrl.includes("youtube.com") || tabUrl.includes("youtu.be")) ? tabUrl : frameUrl;
          let cookies = "";
          try {
            cookies = cookieHeader(await chrome.cookies.getAll({ url: targetUrl }));
          } catch (_e) {}

          let origin = "";
          try {
            origin = new URL(targetUrl).origin;
          } catch (_e) {}

          const payload = {
            url: targetUrl,
            filename: safeName(msg.pageTitle || (tab && tab.title)) || "",
            cookies,
            user_agent: navigator.userAgent,
            referer: targetUrl,
            origin,
            stream_type: "",
            subtitles,
          };

          await sendToDesktop(payload);
          sendResponse({ ok: true });
          return;
        }

        // Look up detected streams for this tab
        let list = (tabId !== null) ? (detectedStreamsByTab.get(tabId) || []) : [];

        if (list.length === 0 && tabId !== null) {
          try {
            const stored = await chrome.storage.session.get(`streams:${tabId}`);
            list = stored[`streams:${tabId}`] || [];
            if (list.length > 0) {
              detectedStreamsByTab.set(tabId, list);
            }
          } catch (_e) {}
        }

        let matched = null;
        for (let i = list.length - 1; i >= 0; i--) {
          if (list[i].frameId === senderFrameId) {
            matched = list[i];
            break;
          }
        }

        if (!matched && list.length > 0) {
          matched = list[list.length - 1];
        }

        if (matched) {
          let cookies = matched.cookies || "";
          if (!cookies && matched.url) {
            try {
              cookies = cookieHeader(await chrome.cookies.getAll({ url: matched.url }));
            } catch (_e) {}
          }

          let origin = matched.origin || "";
          if (!origin && (frameUrl || tabUrl)) {
            try {
              origin = new URL(frameUrl || tabUrl).origin;
            } catch (_e) {}
          }

          const payload = {
            url: matched.url,
            filename: safeName(msg.pageTitle || (tab && tab.title) || matched.filename),
            cookies,
            user_agent: matched.user_agent || navigator.userAgent,
            referer: matched.referer || frameUrl || tabUrl || "",
            origin,
            stream_type: matched.stream_type || "",
            subtitles,
          };

          await sendToDesktop(payload);
          sendResponse({ ok: true });
          return;
        }

        // Fallback to directSrc if present
        if (msg.directSrc && /^https?:\/\//i.test(msg.directSrc)) {
          let cookies = "";
          try {
            cookies = cookieHeader(await chrome.cookies.getAll({ url: msg.directSrc }));
          } catch (_e) {}

          let origin = "";
          try {
            origin = new URL(frameUrl || tabUrl || msg.directSrc).origin;
          } catch (_e) {}

          const payload = {
            url: msg.directSrc,
            filename: safeName(msg.pageTitle || (tab && tab.title)) || defaultFilename(msg.directSrc, "mp4"),
            cookies,
            user_agent: navigator.userAgent,
            referer: frameUrl || tabUrl || "",
            origin,
            stream_type: classifyStreamUrl(msg.directSrc) || "mp4",
            subtitles,
          };

          await sendToDesktop(payload);
          sendResponse({ ok: true });
          return;
        }

        sendResponse({ ok: false, error: "NO_STREAM" });
      } catch (err) {
        sendResponse({ ok: false, error: "OFFLINE" });
      }
    })();
    return true;
  }

  // Handle direct downloadable link clicks from in-page content script
  if (msg.type === "interceptLinkClick") {
    (async () => {
      try {
        const { interceptEnabled } = await chrome.storage.local.get("interceptEnabled");
        if (interceptEnabled === false) {
          sendResponse({ intercepted: false });
          return;
        }

        const running = await isDesktopAppRunning();
        if (!running) {
          sendResponse({ intercepted: false });
          return;
        }

        const url = (msg.url || "").trim();
        if (!/^https?:\/\//i.test(url)) {
          sendResponse({ intercepted: false });
          return;
        }

        let cookies = "";
        try { cookies = cookieHeader(await chrome.cookies.getAll({ url })); } catch (_e) {}

        let origin = "";
        try { origin = new URL(url).origin; } catch (_e) {}

        let filename = msg.downloadAttr || "";
        if (!filename) {
          filename = defaultFilename(url, classifyStreamUrl(url));
        }
        if (!filename && msg.pageTitle) {
          filename = safeName(msg.pageTitle);
        }

        await sendToDesktop({
          url,
          filename,
          cookies,
          user_agent: navigator.userAgent,
          referer: msg.referer || (sender.tab && sender.tab.url) || "",
          origin,
          stream_type: classifyStreamUrl(url) || "",
        });

        sendResponse({ intercepted: true });
      } catch (err) {
        console.warn("Failed to intercept link click:", err);
        sendResponse({ intercepted: false });
      }
    })();
    return true;
  }

  // Handle Quick Download from popup
  if (msg.type === "quickDownload") {
    (async () => {
      try {
        if (!(await isDesktopAppRunning())) {
          throw new Error("CIDM desktop app is offline. Please launch CIDM.");
        }
        const url = (msg.url || "").trim();
        if (!/^https?:\/\//i.test(url)) {
          throw new Error("Invalid URL. Must begin with http:// or https://");
        }

        let cookies = "";
        try { cookies = cookieHeader(await chrome.cookies.getAll({ url })); } catch (_e) {}

        let origin = "";
        try { origin = new URL(url).origin; } catch (_e) {}

        const filename = msg.filename || defaultFilename(url, classifyStreamUrl(url));

        await sendToDesktop({
          url,
          filename,
          cookies,
          user_agent: navigator.userAgent,
          referer: msg.referer || url,
          origin,
          stream_type: classifyStreamUrl(url) || "",
        });

        sendResponse({ ok: true });
      } catch (err) {
        sendResponse({ ok: false, error: String(err.message || err) });
      }
    })();
    return true;
  }

  return false;
});
