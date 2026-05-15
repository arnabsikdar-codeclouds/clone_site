let currentEventSource = null;

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

    btn.disabled = true;
    btn.querySelector("span").textContent = "Cloning...";

    const maxDepth = parseInt(document.getElementById("max-depth").value) || 10;
    const maxPages = parseInt(document.getElementById("max-pages").value) || 500;

    try {
        const resp = await fetch("/api/clone", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url, max_depth: maxDepth, max_pages: maxPages }),
        });

        if (!resp.ok) {
            const err = await resp.json();
            showToast("Error: " + (err.detail || "Failed to start clone"), "error");
            return;
        }

        const data = await resp.json();
        showProgress();
        subscribeToEvents(data.job_id);
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
    updateBadge("crawling");
    updateProgressHeading("Progress", "spinner");
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
                if (data.url) {
                    addLog(`Error: ${shortenUrl(data.url)}`, "error");
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

    // Replace the SVG entirely since innerHTML doesn't work on SVG elements
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

async function refreshJobs() {
    try {
        const resp = await fetch("/api/jobs");
        const jobs = await resp.json();
        renderJobs(jobs);
    } catch (e) {
        console.error("Failed to load jobs:", e);
    }
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
                actions.push(
                    `<button class="primary" onclick="browseJob('${job.job_id}')">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
                        Browse
                    </button>`
                );
                actions.push(
                    `<button onclick="downloadJob('${job.job_id}')">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                        ZIP
                    </button>`
                );
            }
            actions.push(
                `<button class="danger" onclick="deleteJob('${job.job_id}')">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                    Delete
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
    window.open(`/api/jobs/${jobId}/browse/index.html`, "_blank");
}

function downloadJob(jobId) {
    window.location.href = `/api/jobs/${jobId}/download`;
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

// Init on DOM ready
document.addEventListener("DOMContentLoaded", () => {
    refreshJobs();

    document.getElementById("url-input").addEventListener("keydown", (e) => {
        if (e.key === "Enter") startClone();
    });

});
