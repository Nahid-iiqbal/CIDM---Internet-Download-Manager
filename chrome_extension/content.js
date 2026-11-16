// content.js - CIDM In-Page Video Overlay Pill

(function () {
  if (window.__cidmOverlayInjected || window.__pyidmOverlayInjected) {
    return;
  }
  window.__cidmOverlayInjected = true;
  window.__pyidmOverlayInjected = true;

  const MIN_WIDTH = 250;
  const MIN_HEIGHT = 150;
  const HIDE_DELAY_MS = 1500;
  const RESET_DELAY_MS = 2500;

  const SVG_DOWNLOAD_ICON = `
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
      <polyline points="7 10 12 15 17 10"></polyline>
      <line x1="12" y1="15" x2="12" y2="3"></line>
    </svg>
  `;

  const SHADOW_STYLE = `
    :host {
      all: initial !important;
      position: fixed !important;
      top: 0 !important;
      left: 0 !important;
      width: 0 !important;
      height: 0 !important;
      overflow: visible !important;
      z-index: 2147483647 !important;
      pointer-events: none !important;
    }
    .pyidm-pill {
      position: fixed;
      display: inline-flex;
      align-items: center;
      gap: 7px;
      padding: 6px 14px;
      border-radius: 9999px;
      background: rgba(20, 23, 34, 0.92);
      color: #f1f5f9;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      font-size: 12px;
      font-weight: 600;
      line-height: 1;
      letter-spacing: 0.2px;
      box-shadow: 0 4px 16px rgba(0, 0, 0, 0.45), 0 0 0 1px rgba(255, 255, 255, 0.16);
      backdrop-filter: blur(8px);
      -webkit-backdrop-filter: blur(8px);
      cursor: pointer;
      user-select: none;
      -webkit-user-select: none;
      pointer-events: auto;
      opacity: 0;
      transform: translate3d(0, 0, 0);
      transition: opacity 0.25s ease, background-color 0.2s ease, transform 0.15s ease, box-shadow 0.2s ease;
      z-index: 2147483647;
      white-space: nowrap;
    }
    .pyidm-pill:hover {
      background: #2563eb;
      color: #ffffff;
      box-shadow: 0 6px 20px rgba(37, 99, 235, 0.45), 0 0 0 1px rgba(255, 255, 255, 0.25);
      transform: translateY(-1px);
    }
    .pyidm-pill:active {
      transform: translateY(0);
    }
    .pyidm-pill svg {
      flex-shrink: 0;
      display: block;
    }
    .pyidm-pill.busy {
      background: #1d4ed8 !important;
      color: #ffffff !important;
      cursor: wait;
    }
    .pyidm-pill.success {
      background: #059669 !important;
      color: #ffffff !important;
    }
    .pyidm-pill.warn {
      background: #d97706 !important;
      color: #ffffff !important;
    }
    .pyidm-pill.error {
      background: #dc2626 !important;
      color: #ffffff !important;
    }
  `;

  // Map each tracked video element to its overlay controller
  const activeOverlays = new Map();

  class VideoOverlay {
    constructor(video) {
      this.video = video;
      this.isHoveringVideo = false;
      this.isHoveringPill = false;
      this.isBusy = false;
      this.fadeTimer = null;
      this.resetTimer = null;

      // Create outer container element
      this.host = document.createElement("div");
      this.host.className = "pyidm-video-overlay-host";

      // Attach closed shadow root so host page styles cannot penetrate
      this.shadow = this.host.attachShadow({ mode: "closed" });

      const styleEl = document.createElement("style");
      styleEl.textContent = SHADOW_STYLE;

      this.pill = document.createElement("div");
      this.pill.className = "pyidm-pill";
      this.pill.setAttribute("role", "button");
      this.pill.setAttribute("tabindex", "0");
      this.pill.setAttribute("title", "Send video to CIDM Downloader");

      this.iconWrapper = document.createElement("span");
      this.iconWrapper.innerHTML = SVG_DOWNLOAD_ICON;

      this.label = document.createElement("span");
      this.label.textContent = "Download Video";

      this.pill.appendChild(this.iconWrapper);
      this.pill.appendChild(this.label);

      this.shadow.appendChild(styleEl);
      this.shadow.appendChild(this.pill);

      this._bindEvents();
      this.reparent();
      this.updatePosition();

      // Observe video dimension and layout changes
      this.resizeObserver = new ResizeObserver(() => this.updatePosition());
      this.resizeObserver.observe(this.video);
    }

    _bindEvents() {
      // Show when user hovers or moves over video, or video starts playing
      this._onVideoMouseEnter = () => {
        this.isHoveringVideo = true;
        this.show();
      };
      this._onVideoMouseMove = () => {
        this.isHoveringVideo = true;
        this.show();
      };
      this._onVideoMouseLeave = () => {
        this.isHoveringVideo = false;
        this.scheduleHide();
      };
      this._onVideoPlay = () => {
        this.show();
        this.scheduleHide();
      };

      this.video.addEventListener("mouseenter", this._onVideoMouseEnter);
      this.video.addEventListener("mousemove", this._onVideoMouseMove);
      this.video.addEventListener("mouseleave", this._onVideoMouseLeave);
      this.video.addEventListener("play", this._onVideoPlay);

      // Keep pill visible while hovering over the pill itself
      this.pill.addEventListener("mouseenter", () => {
        this.isHoveringPill = true;
        this.show();
      });
      this.pill.addEventListener("mouseleave", () => {
        this.isHoveringPill = false;
        this.scheduleHide();
      });

      // Handle download click action
      this.pill.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation();
        this._handleClick();
      });
    }

    show() {
      if (this.fadeTimer) {
        clearTimeout(this.fadeTimer);
        this.fadeTimer = null;
      }
      this.updatePosition();
      this.pill.style.opacity = "1";
    }

    scheduleHide() {
      if (this.fadeTimer) {
        clearTimeout(this.fadeTimer);
      }
      this.fadeTimer = setTimeout(() => {
        if (!this.isHoveringVideo && !this.isHoveringPill && !this.isBusy) {
          this.pill.style.opacity = "0";
        }
      }, HIDE_DELAY_MS);
    }

    updatePosition() {
      if (!this.video.isConnected) {
        this.destroy();
        return;
      }

      // Check if video is visibly displayed
      const style = window.getComputedStyle(this.video);
      if (style.display === "none" || style.visibility === "hidden" || parseFloat(style.opacity || "1") <= 0) {
        this.pill.style.display = "none";
        return;
      }

      const rect = this.video.getBoundingClientRect();
      if (rect.width < MIN_WIDTH || rect.height < MIN_HEIGHT) {
        this.pill.style.display = "none";
        return;
      }

      // Check if video is within window viewport
      const inView =
        rect.bottom > 0 &&
        rect.top < window.innerHeight &&
        rect.right > 0 &&
        rect.left < window.innerWidth;

      if (!inView) {
        this.pill.style.display = "none";
        return;
      }

      this.pill.style.display = "inline-flex";

      // Anchor to the top-right corner of the video
      const topOffset = Math.max(8, Math.min(window.innerHeight - 44, rect.top + 12));
      const rightOffset = Math.max(8, Math.min(window.innerWidth - 80, window.innerWidth - rect.right + 12));

      this.pill.style.top = `${topOffset}px`;
      this.pill.style.right = `${rightOffset}px`;
    }

    reparent() {
      // In fullscreen mode, append host inside the fullscreen element so it stays visible
      const targetParent = document.fullscreenElement || document.documentElement || document.body;
      if (targetParent && this.host.parentElement !== targetParent) {
        targetParent.appendChild(this.host);
      }
    }

    setFeedback(text, statusClass) {
      this.label.textContent = text;
      this.pill.classList.remove("busy", "success", "warn", "error");
      if (statusClass) {
        this.pill.classList.add(statusClass);
      }
    }

    resetFeedback() {
      this.setFeedback("Download Video", "");
      this.isBusy = false;
      if (!this.isHoveringVideo && !this.isHoveringPill) {
        this.scheduleHide();
      }
    }

    _handleClick() {
      if (this.isBusy) return;
      this.isBusy = true;

      if (this.resetTimer) {
        clearTimeout(this.resetTimer);
        this.resetTimer = null;
      }

      this.setFeedback("Sending...", "busy");
      this.show();

      // Only pass currentSrc if it is a direct non-blob HTTP/HTTPS URL
      let directSrc = "";
      try {
        const src = this.video.currentSrc || this.video.src || "";
        if (src && !src.startsWith("blob:") && /^https?:\/\//i.test(src)) {
          directSrc = src;
        }
      } catch (_) {}

      const message = {
        type: "CIDM_DOWNLOAD_FRAME_VIDEO",
        directSrc: directSrc,
        pageTitle: document.title || "",
        frameUrl: window.location.href,
      };

      try {
        chrome.runtime.sendMessage(message, (response) => {
          if (chrome.runtime.lastError) {
            this.setFeedback("CIDM Offline", "error");
            this.resetTimer = setTimeout(() => this.resetFeedback(), RESET_DELAY_MS);
            return;
          }

          if (response && response.ok) {
            this.setFeedback("Sent to CIDM!", "success");
          } else if (response && response.error === "NO_STREAM") {
            this.setFeedback("Play video first", "warn");
          } else if (response && (response.error === "OFFLINE" || response.error?.includes("offline"))) {
            this.setFeedback("CIDM Offline", "error");
          } else {
            const errText = response && response.error ? response.error.slice(0, 18) : "Play video first";
            this.setFeedback(errText, "warn");
          }

          this.resetTimer = setTimeout(() => this.resetFeedback(), RESET_DELAY_MS);
        });
      } catch (err) {
        this.setFeedback("CIDM Offline", "error");
        this.resetTimer = setTimeout(() => this.resetFeedback(), RESET_DELAY_MS);
      }
    }

    destroy() {
      if (this.fadeTimer) clearTimeout(this.fadeTimer);
      if (this.resetTimer) clearTimeout(this.resetTimer);
      if (this.resizeObserver) this.resizeObserver.disconnect();

      this.video.removeEventListener("mouseenter", this._onVideoMouseEnter);
      this.video.removeEventListener("mousemove", this._onVideoMouseMove);
      this.video.removeEventListener("mouseleave", this._onVideoMouseLeave);
      this.video.removeEventListener("play", this._onVideoPlay);

      try {
        this.host.remove();
      } catch (_) {}

      activeOverlays.delete(this.video);
    }
  }

  function attachOverlayToVideo(video) {
    if (!video || activeOverlays.has(video)) return;
    try {
      const overlay = new VideoOverlay(video);
      activeOverlays.set(video, overlay);
    } catch (err) {
      console.debug("[PyIDM Overlay] Failed to attach overlay:", err);
    }
  }

  function scanAndAttach() {
    document.querySelectorAll("video").forEach(attachOverlayToVideo);
  }

  function updateAllOverlays() {
    for (const [video, overlay] of activeOverlays.entries()) {
      if (!video.isConnected) {
        overlay.destroy();
      } else {
        overlay.updatePosition();
      }
    }
  }

  function reparentAllOverlays() {
    for (const [video, overlay] of activeOverlays.entries()) {
      if (!video.isConnected) {
        overlay.destroy();
      } else {
        overlay.reparent();
        overlay.updatePosition();
      }
    }
  }

  // Initial scan
  scanAndAttach();

  // Watch for dynamically added <video> tags in single-page apps or lazy players
  const mutationObserver = new MutationObserver((mutations) => {
    for (const m of mutations) {
      for (const node of m.addedNodes) {
        if (node.nodeType === Node.ELEMENT_NODE) {
          if (node.tagName === "VIDEO") {
            attachOverlayToVideo(node);
          } else if (node.querySelectorAll) {
            node.querySelectorAll("video").forEach(attachOverlayToVideo);
          }
        }
      }
    }
  });

  if (document.documentElement) {
    mutationObserver.observe(document.documentElement, { childList: true, subtree: true });
  }

  // Continuously update position during scroll and resize
  window.addEventListener("scroll", updateAllOverlays, { capture: true, passive: true });
  window.addEventListener("resize", updateAllOverlays, { passive: true });

  // Handle native HTML5 fullscreen changes
  document.addEventListener("fullscreenchange", reparentAllOverlays);
  document.addEventListener("webkitfullscreenchange", reparentAllOverlays);

  // ---------------------------------------------------------------------------
  // Universal Link Click Interception (All File Types: ZIP, EXE, ISO, PDF, etc.)
  // ---------------------------------------------------------------------------
  const DOWNLOAD_EXTENSIONS_REGEX = /\.(zip|rar|7z|tar|gz|bz2|xz|iso|img|dmg|pkg|exe|msi|bin|apk|deb|rpm|pdf|djvu|doc|docx|xls|xlsx|ppt|pptx|csv|epub|mobi|mp3|flac|wav|aac|ogg|m4a|wma|mp4|mkv|webm|avi|mov|wmv|flv|torrent)(?:$|[?#])/i;

  document.addEventListener("click", async (e) => {
    // Only intercept primary mouse button (left-click) without modifier keys
    if (e.button !== 0 || e.defaultPrevented || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) {
      return;
    }
    const anchor = e.target.closest("a[href]");
    if (!anchor || !anchor.href) return;

    const href = anchor.href;
    if (!/^https?:\/\//i.test(href)) return;

    let isDownloadable = false;
    const hasDownloadAttr = anchor.hasAttribute("download");
    if (hasDownloadAttr) {
      isDownloadable = true;
    } else {
      try {
        const u = new URL(href);
        if (DOWNLOAD_EXTENSIONS_REGEX.test(u.pathname)) {
          isDownloadable = true;
        }
      } catch (_e) {}
    }

    if (!isDownloadable) return;

    // Check with background worker if CIDM is online and intercept is enabled
    try {
      const resp = await chrome.runtime.sendMessage({
        type: "interceptLinkClick",
        url: href,
        downloadAttr: anchor.getAttribute("download") || "",
        linkText: (anchor.textContent || "").trim().slice(0, 80),
        pageTitle: document.title || "",
        referer: window.location.href,
      });
      if (resp && resp.intercepted) {
        e.preventDefault();
        e.stopPropagation();
      }
    } catch (_err) {
      // Background worker unreachable or offline; continue standard browser behavior
    }
  }, true);
})();
