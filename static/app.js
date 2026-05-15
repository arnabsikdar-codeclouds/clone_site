let currentEventSource = null;
let currentJobId = null;
let allJobs = [];
let currentErrors = [];
let loginSessionId = null;
let loginCookies = null;
let loginDiscoveredUrls = null;
let loginPollTimer = null;

async function startClone() {
    const urlInput = document.getElementById("url-input");
    const btn = document.getElementById("clone-btn");
    const url = urlInput.value.trim();

    if (!url) {
        urlInput.focus();
        urlInput.parentElement.style.animation = "shake 0.4s ease";
        setTimeout(() => (urlInput.parentElement.style.animation = ""), 400);
        return;
    }

    // Duplicate job detection (D2) — check client-side
    const existing = allJobs.find(
        (j) => j.status === "done" && j.url === url
    );
    if (existing) {
        if (!confirm(`This URL was already cloned (job ${existing.job_id}). Clone again?`)) {
            return;
        }
    }

    btn.disabled = true;
    btn.querySelector("span").textContent = "Cloning...";

    const maxDepth = parseInt(document.getElementById("max-depth").value) || 10;
    const maxPages = parseInt(document.getElementById("max-pages").value) || 500;
    const verifySSL = document.getElementById("verify-ssl").checked;
    const usePlaywright = document.getElementById("use-playwright").checked;

    try {
        const resp = await fetch("/api/clone", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                url,
                max_depth: maxDepth,
                max_pages: maxPages,
                verify_ssl: verifySSL,
                use_playwright: usePlaywright,
                auth_cookies: loginCookies || undefined,
                seed_urls: loginDiscoveredUrls && loginDiscoveredUrls.length ? loginDiscoveredUrls : undefined,
            }),
        });

        if (!resp.ok) {
            const err = await resp.json();
            showToast("Error: " + (err.detail || "Failed to start clone"), "error");
            return;
        }

        const data = await resp.json();
        if (data.warning) {
            showToast(data.warning, "info");
        }
        currentJobId = data.job_id;
        showProgress();
        subscribeToEvents(data.job_id);
        if (loginCookies) clearLoginSession();
    } catch (e) {
        showToast("Error: " + e.message, "error");
    } finally {
        btn.disabled = false;
        btn.querySelector("span").textContent = "Clone";
    }
}

function showProgress() {
    const section = document.getElementById("progress-section");
    section.classList.remove("hidden");
    document.getElementById("pages-count").textContent = "0";
    document.getElementById("assets-count").textContent = "0";
    document.getElementById("errors-count").textContent = "0";
    document.getElementById("progress-bar").style.width = "0%";
    document.getElementById("progress-pct").textContent = "0%";
    document.getElementById("event-log").innerHTML = "";
    document.getElementById("error-list").innerHTML = "";
    document.getElementById("error-panel").classList.add("hidden");
    currentErrors = [];
    updateBadge("crawling");
    updateProgressHeading("Progress", "spinner");

    // Show cancel button
    const cancelBtn = document.getElementById("cancel-btn");
    cancelBtn.classList.remove("hidden");

    section.scrollIntoView({ behavior: "smooth", block: "start" });
}

function subscribeToEvents(jobId) {
    if (currentEventSource) {
        currentEventSource.close();
    }

    const es = new EventSource(`/api/jobs/${jobId}/events`);
    currentEventSource = es;

    let errorsCount = 0;

    es.onmessage = (event) => {
        const data = JSON.parse(event.data);

        switch (data.type) {
            case "status":
                updateBadge(data.status);
                if (data.status === "cancelled") {
                    updateProgressHeading("Cancelled", "cancelled");
                    addLog("Clone cancelled by user", "error");
                    hideCancelButton();
                    refreshJobs();
                    hideProgressAfterDelay();
                }
                break;

            case "page_crawled":
                animateValue("pages-count", data.pages_crawled);
                addLog(`Crawled: ${shortenUrl(data.url)} (depth ${data.depth})`);
                break;

            case "crawl_complete":
                addLog(`Crawl complete: ${data.pages_crawled} pages, ${data.assets_found} assets found`, "success");
                break;

            case "asset_downloaded":
                animateValue("assets-count", data.assets_downloaded);
                if (data.assets_total > 0) {
                    const pct = Math.round((data.assets_downloaded / data.assets_total) * 100);
                    document.getElementById("progress-bar").style.width = pct + "%";
                    document.getElementById("progress-pct").textContent = pct + "%";
                }
                break;

            case "secondary_assets_found":
                addLog(`Found ${data.count} secondary assets (fonts, images from CSS)`);
                break;

            case "error":
                errorsCount++;
                animateValue("errors-count", errorsCount);
                // Collect error details
                if (data.url) {
                    currentErrors.push({
                        url: data.url,
                        category: data.category || "unknown",
                        message: data.error || "Unknown error",
                    });
                    addLog(`Error: ${shortenUrl(data.url)} [${data.category || "unknown"}]`, "error");
                } else if (data.error) {
                    addLog(`Error: ${data.error}`, "error");
                }
                break;

            case "done":
                document.getElementById("progress-bar").style.width = "100%";
                document.getElementById("progress-pct").textContent = "100%";
                updateBadge("done");
                updateProgressHeading("Complete", "done");
                addLog(
                    `Done! ${data.pages_crawled} pages, ${data.assets_downloaded} assets, ${data.errors} errors`,
                    "success"
                );
                hideCancelButton();
                refreshJobs();
                es.close();
                hideProgressAfterDelay();
                break;

            case "end":
                if (data.status === "failed") {
                    updateBadge("failed");
                    updateProgressHeading("Failed", "failed");
                    addLog("Clone failed!", "error");
                }
                hideCancelButton();
                refreshJobs();
                es.close();
                hideProgressAfterDelay();
                break;
        }
    };

    es.onerror = () => {
        es.close();
    };
}

function hideCancelButton() {
    document.getElementById("cancel-btn").classList.add("hidden");
}

async function cancelCurrentJob() {
    if (!currentJobId) return;
    try {
        const resp = await fetch(`/api/jobs/${currentJobId}/cancel`, { method: "POST" });
        if (!resp.ok) {
            const err = await resp.json();
            showToast("Error: " + (err.detail || "Failed to cancel"), "error");
        }
    } catch (e) {
        showToast("Error: " + e.message, "error");
    }
}

function toggleErrorPanel() {
    const panel = document.getElementById("error-panel");
    if (panel.classList.contains("hidden")) {
        // Populate error list
        const list = document.getElementById("error-list");
        if (currentErrors.length === 0) {
            list.innerHTML = '<div class="error-item" style="color:var(--text-muted)">No errors yet</div>';
        } else {
            list.innerHTML = currentErrors
                .map(
                    (e) => `
                <div class="error-item">
                    <span class="error-category">${escapeHtml(e.category)}</span>
                    <span>${escapeHtml(shortenUrl(e.url))}: ${escapeHtml(e.message)}</span>
                </div>`
                )
                .join("");
        }
        panel.classList.remove("hidden");
    } else {
        panel.classList.add("hidden");
    }
}

function hideProgressAfterDelay() {
    setTimeout(() => {
        const section = document.getElementById("progress-section");
        section.style.transition = "opacity 0.4s ease, transform 0.4s ease";
        section.style.opacity = "0";
        section.style.transform = "translateY(-10px)";
        setTimeout(() => {
            section.classList.add("hidden");
            section.style.opacity = "";
            section.style.transform = "";
            section.style.transition = "";
        }, 400);
    }, 2000);
}

function updateProgressHeading(text, state) {
    const title = document.getElementById("progress-title");
    const heading = document.getElementById("progress-heading");
    title.textContent = text;

    const oldIcon = heading.querySelector("svg");
    if (oldIcon) oldIcon.remove();

    const svgNS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("width", "18");
    svg.setAttribute("height", "18");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.classList.add("progress-spinner");

    if (state === "done") {
        svg.classList.add("done");
        const pl = document.createElementNS(svgNS, "polyline");
        pl.setAttribute("points", "20 6 9 17 4 12");
        svg.appendChild(pl);
    } else if (state === "failed") {
        svg.classList.add("failed");
        const c = document.createElementNS(svgNS, "circle");
        c.setAttribute("cx", "12"); c.setAttribute("cy", "12"); c.setAttribute("r", "10");
        const l1 = document.createElementNS(svgNS, "line");
        l1.setAttribute("x1", "15"); l1.setAttribute("y1", "9"); l1.setAttribute("x2", "9"); l1.setAttribute("y2", "15");
        const l2 = document.createElementNS(svgNS, "line");
        l2.setAttribute("x1", "9"); l2.setAttribute("y1", "9"); l2.setAttribute("x2", "15"); l2.setAttribute("y2", "15");
        svg.append(c, l1, l2);
    } else if (state === "cancelled") {
        svg.classList.add("cancelled");
        const c = document.createElementNS(svgNS, "circle");
        c.setAttribute("cx", "12"); c.setAttribute("cy", "12"); c.setAttribute("r", "10");
        const l1 = document.createElementNS(svgNS, "line");
        l1.setAttribute("x1", "8"); l1.setAttribute("y1", "12"); l1.setAttribute("x2", "16"); l1.setAttribute("y2", "12");
        svg.append(c, l1);
    } else {
        const lines = [
            ["12","2","12","6"], ["12","18","12","22"],
            ["4.93","4.93","7.76","7.76"], ["16.24","16.24","19.07","19.07"],
            ["2","12","6","12"], ["18","12","22","12"],
            ["4.93","19.07","7.76","16.24"], ["16.24","7.76","19.07","4.93"]
        ];
        for (const [x1,y1,x2,y2] of lines) {
            const l = document.createElementNS(svgNS, "line");
            l.setAttribute("x1", x1); l.setAttribute("y1", y1);
            l.setAttribute("x2", x2); l.setAttribute("y2", y2);
            svg.appendChild(l);
        }
    }

    heading.insertBefore(svg, title);
}

function updateBadge(status) {
    const badge = document.getElementById("status-badge");
    badge.textContent = status;
    badge.className = "badge " + status;
}

function animateValue(elementId, newValue) {
    const el = document.getElementById(elementId);
    el.textContent = newValue;
    el.style.transform = "scale(1.15)";
    el.style.transition = "transform 0.15s ease";
    setTimeout(() => {
        el.style.transform = "scale(1)";
    }, 150);
}

function addLog(message, type = "") {
    const log = document.getElementById("event-log");
    const entry = document.createElement("div");
    entry.className = "log-entry" + (type ? " " + type : "");

    const time = document.createElement("span");
    time.className = "log-time";
    time.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

    const text = document.createElement("span");
    text.textContent = message;

    entry.appendChild(time);
    entry.appendChild(text);
    log.appendChild(entry);
    log.scrollTop = log.scrollHeight;
}

function shortenUrl(url) {
    try {
        const u = new URL(url);
        const path = u.pathname + u.search;
        return path.length > 60 ? path.slice(0, 57) + "..." : path;
    } catch {
        return url.length > 60 ? url.slice(0, 57) + "..." : url;
    }
}

function formatSize(bytes) {
    if (bytes === 0) return "";
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

async function refreshJobs() {
    try {
        const resp = await fetch("/api/jobs");
        allJobs = await resp.json();
        applyFilters();
    } catch (e) {
        console.error("Failed to load jobs:", e);
    }
}

function applyFilters() {
    const search = (document.getElementById("filter-search").value || "").toLowerCase();
    const status = document.getElementById("filter-status").value;

    let filtered = allJobs;
    if (search) {
        filtered = filtered.filter((j) => j.url.toLowerCase().includes(search) || j.domain.toLowerCase().includes(search));
    }
    if (status) {
        filtered = filtered.filter((j) => j.status === status);
    }
    renderJobs(filtered);
}

function renderJobs(jobs) {
    const container = document.getElementById("job-list");

    if (!jobs.length) {
        container.innerHTML = `
            <div class="empty-state">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" stroke-linecap="round" stroke-linejoin="round" opacity="0.3">
                    <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><polyline points="13 2 13 9 20 9"/>
                </svg>
                <p>No cloned sites yet</p>
                <span>Enter a URL above to get started</span>
            </div>`;
        return;
    }

    container.innerHTML = jobs
        .slice()
        .reverse()
        .map((job) => {
            const actions = [];
            if (job.status === "done") {
                // Preview button (E4)
                actions.push(
                    `<button class="primary" onclick="previewJob('${job.job_id}', '${escapeHtml(job.domain)}')">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                        Preview
                    </button>`
                );
                actions.push(
                    `<button onclick="browseJob('${job.job_id}')">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
                        Browse
                    </button>`
                );
                const sizeLabel = job.site_size_bytes ? ` (${formatSize(job.site_size_bytes)})` : "";
                actions.push(
                    `<button onclick="downloadJob('${job.job_id}')">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                        ZIP${sizeLabel}
                    </button>`
                );
            }
            // Retry button for failed/cancelled jobs (E3)
            if (job.status === "failed" || job.status === "cancelled") {
                actions.push(
                    `<button class="retry-btn" onclick="retryJob('${escapeAttr(job.url)}')">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
                        Retry
                    </button>`
                );
            }
            actions.push(
                `<button class="danger" onclick="deleteJob('${job.job_id}')">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                </button>`
            );
            return `
                <div class="job-card">
                    <div class="job-info">
                        <span class="job-url">${escapeHtml(job.url)}</span>
                        <div class="job-meta">
                            <span class="badge ${job.status}">${job.status}</span>
                            <div class="job-stats">
                                <span>
                                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/></svg>
                                    ${job.pages_crawled}
                                </span>
                                <span>
                                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
                                    ${job.assets_downloaded}
                                </span>
                                ${job.errors_count > 0 ? `<span style="color:var(--red)">
                                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/></svg>
                                    ${job.errors_count}
                                </span>` : ""}
                                ${job.site_size_bytes ? `<span class="job-size">${formatSize(job.site_size_bytes)}</span>` : ""}
                            </div>
                        </div>
                    </div>
                    <div class="job-actions">
                        ${actions.join("")}
                    </div>
                </div>`;
        })
        .join("");
}

function browseJob(jobId) {
    window.open(`/site/${jobId}/index.html`, "_blank");
}

function downloadJob(jobId) {
    window.location.href = `/api/jobs/${jobId}/download`;
}

// E3: Retry failed job
function retryJob(url) {
    document.getElementById("url-input").value = url;
    startClone();
}

// E4: In-app preview
let currentPreviewUrl = "";

function previewJob(jobId, domain) {
    const url = `/api/jobs/${jobId}/browse/index.html?embed=1`;
    currentPreviewUrl = `/site/${jobId}/index.html`;
    document.getElementById("preview-title").textContent = `Preview: ${domain}`;
    document.getElementById("preview-iframe").src = url;
    document.getElementById("preview-modal").classList.remove("hidden");
}

function closePreview() {
    document.getElementById("preview-modal").classList.add("hidden");
    document.getElementById("preview-iframe").src = "";
    currentPreviewUrl = "";
}

function closePreviewOnOverlay(e) {
    if (e.target === document.getElementById("preview-modal")) {
        closePreview();
    }
}

function openPreviewInTab() {
    if (currentPreviewUrl) {
        window.open(currentPreviewUrl, "_blank");
    }
}

async function deleteJob(jobId) {
    if (!confirm("Delete this cloned site?")) return;
    try {
        const resp = await fetch(`/api/jobs/${jobId}`, { method: "DELETE" });
        if (!resp.ok) {
            const err = await resp.json();
            showToast("Error: " + (err.detail || "Failed to delete"), "error");
            return;
        }
        showToast("Deleted successfully");
        refreshJobs();
    } catch (e) {
        showToast("Error: " + e.message, "error");
    }
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

function escapeAttr(text) {
    return text.replace(/'/g, "\\'").replace(/"/g, "&quot;");
}

function showToast(message, type = "info") {
    const toast = document.createElement("div");
    toast.style.cssText = `
        position: fixed; bottom: 1.5rem; right: 1.5rem; z-index: 9999;
        padding: 0.75rem 1.25rem; border-radius: 10px;
        font-size: 0.85rem; font-weight: 500;
        background: ${type === "error" ? "var(--red-bg)" : "var(--bg-card)"};
        color: ${type === "error" ? "var(--red)" : "var(--text-primary)"};
        border: 1px solid ${type === "error" ? "rgba(239,68,68,0.3)" : "var(--border)"};
        box-shadow: 0 8px 32px rgba(0,0,0,0.4);
        backdrop-filter: blur(12px);
        animation: slideUp 0.3s ease;
    `;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transition = "opacity 0.3s ease";
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// ===== Login Flow =====
async function startLoginSession() {
    const url = document.getElementById("url-input").value.trim();
    if (!url) {
        showToast("Enter a URL first", "error");
        document.getElementById("url-input").focus();
        return;
    }

    const statusEl = document.getElementById("auth-status");
    const statusText = document.getElementById("auth-status-text");
    const doneBtn = document.getElementById("auth-done-btn");

    statusEl.classList.remove("hidden");
    statusText.textContent = "Launching browser...";
    doneBtn.classList.add("hidden");

    try {
        const resp = await fetch("/api/auth/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url }),
        });
        if (!resp.ok) {
            const err = await resp.json();
            statusText.textContent = "Failed";
            showToast("Login error: " + (err.detail || "Unknown"), "error");
            return;
        }
        const data = await resp.json();
        loginSessionId = data.session_id;

        // Poll until browser is actually open before showing Done button
        if (loginPollTimer) clearInterval(loginPollTimer);
        loginPollTimer = setInterval(async () => {
            try {
                const sr = await fetch(`/api/auth/login/${loginSessionId}`);
                const sd = await sr.json();
                if (sd.status === "browser_open") {
                    clearInterval(loginPollTimer);
                    loginPollTimer = null;
                    statusText.textContent = "Browser open — log in, then click Done";
                    doneBtn.classList.remove("hidden");
                } else if (sd.status === "failed") {
                    clearInterval(loginPollTimer);
                    loginPollTimer = null;
                    statusText.textContent = "Failed";
                    showToast("Login error: " + (sd.error || "Browser launch failed"), "error");
                } else if (sd.status === "done" || sd.status === "expired") {
                    clearInterval(loginPollTimer);
                    loginPollTimer = null;
                    statusText.textContent = sd.error || "Session ended";
                }
            } catch {
                // ignore transient errors
            }
        }, 500);
    } catch (e) {
        statusText.textContent = "Failed";
        showToast("Login error: " + e.message, "error");
    }
}

async function finishLoginSession() {
    if (!loginSessionId) return;

    const statusText = document.getElementById("auth-status-text");
    const doneBtn = document.getElementById("auth-done-btn");
    doneBtn.classList.add("hidden");
    statusText.textContent = "Extracting cookies...";

    try {
        const resp = await fetch(`/api/auth/login/${loginSessionId}/done`, { method: "POST" });
        if (!resp.ok) {
            const err = await resp.json();
            statusText.textContent = "Failed";
            showToast("Error: " + (err.detail || "Unknown"), "error");
            return;
        }
    } catch (e) {
        statusText.textContent = "Failed";
        showToast("Error: " + e.message, "error");
        return;
    }

    // Poll until done
    if (loginPollTimer) clearInterval(loginPollTimer);
    loginPollTimer = setInterval(async () => {
        try {
            const resp = await fetch(`/api/auth/login/${loginSessionId}`);
            const data = await resp.json();
            if (data.status === "done") {
                clearInterval(loginPollTimer);
                loginPollTimer = null;
                loginCookies = data.cookies;
                loginDiscoveredUrls = data.discovered_urls || [];
                const count = Object.keys(data.cookies).length;
                const urlCount = loginDiscoveredUrls.length;
                statusText.textContent = `Logged in (${count} cookie${count !== 1 ? "s" : ""}` +
                    (urlCount ? `, ${urlCount} page${urlCount !== 1 ? "s" : ""} found` : "") + `)`;
                statusText.classList.add("auth-success");
            } else if (data.status === "failed" || data.status === "expired") {
                clearInterval(loginPollTimer);
                loginPollTimer = null;
                statusText.textContent = data.error || "Session " + data.status;
                showToast("Login session " + data.status, "error");
            }
        } catch {
            // ignore transient fetch errors
        }
    }, 1000);
}

function clearLoginSession() {
    if (loginPollTimer) {
        clearInterval(loginPollTimer);
        loginPollTimer = null;
    }
    loginSessionId = null;
    loginCookies = null;
    loginDiscoveredUrls = null;
    document.getElementById("auth-status").classList.add("hidden");
    document.getElementById("auth-done-btn").classList.add("hidden");
    const statusText = document.getElementById("auth-status-text");
    statusText.textContent = "";
    statusText.classList.remove("auth-success");
}

// Init on DOM ready
document.addEventListener("DOMContentLoaded", () => {
    refreshJobs();

    document.getElementById("url-input").addEventListener("keydown", (e) => {
        if (e.key === "Enter") startClone();
    });

    // Escape key closes preview modal
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            closePreview();
        }
    });
});
