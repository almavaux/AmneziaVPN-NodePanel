const modal = document.getElementById("addNodeModal");
const addNodeBtn = document.getElementById("addNodeBtn");
const panelVersionBadge = document.getElementById("panelVersionBadge");
const modeAutoBtn = document.getElementById("modeAutoBtn");
const modeManualBtn = document.getElementById("modeManualBtn");
const backBtn1 = document.getElementById("backBtn1");
const backBtn2 = document.getElementById("backBtn2");
const installBtn = document.getElementById("installBtn");
const createBootstrapBtn = document.getElementById("createBootstrapBtn");
const closeModalBtn = document.getElementById("closeModal");
const dismissAddNodeModalBtn = document.getElementById("dismissAddNodeModal");
const nodesGrid = document.getElementById("nodesGrid");
const progressFill = document.getElementById("progressFill");
const progressMsg = document.getElementById("progressMsg");
const installLog = document.getElementById("installLog");
const copyBootstrapBtn = document.getElementById("copyBootstrapBtn");
const bootstrapCmd = document.getElementById("bootstrapCmd");
const nodeDetailsModal = document.getElementById("nodeDetailsModal");
const nodeModalTitle = document.getElementById("nodeModalTitle");
const nodeModalMeta = document.getElementById("nodeModalMeta");
const dismissNodeModalBtn = document.getElementById("dismissNodeModal");
const closeNodeModalBtn = document.getElementById("closeNodeModal");
const nodeUsersState = document.getElementById("nodeUsersState");
const nodeUsersList = document.getElementById("nodeUsersList");
const nodeUserNameInput = document.getElementById("nodeUserName");
const createNodeUserBtn = document.getElementById("createNodeUserBtn");
const refreshNodeUsersBtn = document.getElementById("refreshNodeUsersBtn");
const updateNodeBtn = document.getElementById("updateNodeBtn");
const nodeUserPreview = document.getElementById("nodeUserPreview");
const nodeUserPreviewTitle = document.getElementById("nodeUserPreviewTitle");
const nodeUserPreviewBody = document.getElementById("nodeUserPreviewBody");
const clearNodePreviewBtn = document.getElementById("clearNodePreviewBtn");
const qrModal = document.getElementById("qrModal");
const qrModalTitle = document.getElementById("qrModalTitle");
const qrModalImage = document.getElementById("qrModalImage");
const closeQrModalBtn = document.getElementById("closeQrModalBtn");

let currentMode = null;
let nodesById = new Map();
let selectedNodeId = null;
let previewImageUrl = null;
let qrModalImageUrl = null;

function getAppBasePath() {
  return window.location.pathname
    .replace(/\/index\.html$/, "/")
    .replace(/\/panel\/?$/, "/");
}

function getApiUrl(path) {
  const normalizedPath = path.replace(/^\/+/, "");
  return new URL(normalizedPath, `${window.location.origin}${getAppBasePath()}`).toString();
}

function getApiUrlWithParams(path, params = {}) {
  const url = new URL(getApiUrl(path));
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, value);
    }
  });
  return url.toString();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

async function parseErrorResponse(response) {
  const contentType = response.headers.get("content-type") || "";

  if (contentType.includes("application/json")) {
    const payload = await response.json().catch(() => ({}));
    return payload.detail || payload.message || `HTTP ${response.status}`;
  }

  const text = await response.text().catch(() => "");
  return text || `HTTP ${response.status}`;
}

function revokePreviewImage() {
  if (previewImageUrl) {
    URL.revokeObjectURL(previewImageUrl);
    previewImageUrl = null;
  }
}

function revokeQrModalImage() {
  if (qrModalImageUrl) {
    URL.revokeObjectURL(qrModalImageUrl);
    qrModalImageUrl = null;
  }
}

function showStep(stepId, progress) {
  document.querySelectorAll(".wizard-step").forEach((step) => step.classList.remove("active"));
  document.getElementById(stepId).classList.add("active");
  progressFill.style.width = `${progress}%`;
}

function resetProgressMessage() {
  progressMsg.classList.remove("progress-message-success", "progress-message-error");
}

function setProgressMessage(message, type) {
  resetProgressMessage();
  progressMsg.textContent = message;

  if (type === "success") {
    progressMsg.classList.add("progress-message-success");
  }

  if (type === "error") {
    progressMsg.classList.add("progress-message-error");
  }
}

function emptyStateMarkup() {
  return '<div class="card empty-state"><p class="small">No nodes yet. Add one to get started.</p></div>';
}

function openModal() {
  currentMode = null;
  document.getElementById("nodeName").value = "";
  document.getElementById("nodeIp").value = "";
  document.getElementById("sshUser").value = "root";
  document.getElementById("sshPassword").value = "";
  document.getElementById("nodeNameManual").value = "";
  document.getElementById("nodeIpManual").value = "";
  bootstrapCmd.textContent = "bash -c '$(curl -fsSL http://panel:8000/install)' -- TOKEN MASTER_IP";
  installLog.textContent = "";
  resetProgressMessage();
  progressMsg.textContent = "Installation in progress...";
  showStep("step1", 33);
  modal.classList.add("open");
}

function closeAddNodeModal() {
  modal.classList.remove("open");
  loadNodes();
}

function updateNodeUsersState(message, tone) {
  nodeUsersState.textContent = message;
  nodeUsersState.classList.remove("is-error", "is-success");

  if (tone === "error") {
    nodeUsersState.classList.add("is-error");
  }

  if (tone === "success") {
    nodeUsersState.classList.add("is-success");
  }
}

function clearNodePreview() {
  revokePreviewImage();
  nodeUserPreview.hidden = true;
  nodeUserPreviewTitle.textContent = "Preview";
  nodeUserPreviewBody.innerHTML = "";
}

function showConfigPreview(title, configText) {
  clearNodePreview();
  nodeUserPreview.hidden = false;
  nodeUserPreviewTitle.textContent = title;
  nodeUserPreviewBody.innerHTML = `
    <div class="config-preview-toolbar">
      <button id="copyFullConfigBtn" class="ghost" type="button">Copy full config</button>
    </div>
    <pre class="config-preview">${escapeHtml(configText)}</pre>
  `;

  const copyBtn = document.getElementById("copyFullConfigBtn");
  if (copyBtn) {
    copyBtn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(configText);
        updateNodeUsersState("Config copied to clipboard.", "success");
      } catch (error) {
        updateNodeUsersState(`Failed to copy config: ${error.message}`, "error");
      }
    });
  }

  nodeUserPreview.scrollIntoView({ behavior: "smooth", block: "start" });
}

function showQrPreview(title, blob) {
  revokeQrModalImage();
  qrModalImageUrl = URL.createObjectURL(blob);
  qrModalTitle.textContent = title;
  qrModalImage.src = qrModalImageUrl;
  qrModal.classList.add("open");
}

function closeQrModal() {
  qrModal.classList.remove("open");
  qrModalImage.removeAttribute("src");
  revokeQrModalImage();
}

function getSelectedNode() {
  return selectedNodeId ? nodesById.get(selectedNodeId) : null;
}

function renderNodeMeta(node) {
  nodeModalTitle.textContent = `${node.name} users`;
  nodeModalMeta.innerHTML = [
    `<span class="meta-chip">IP: ${escapeHtml(node.ip)}</span>`,
    `<span class="meta-chip">Status: ${escapeHtml(node.status)}</span>`,
    `<span class="meta-chip">Version: ${escapeHtml(node.node_version || "N0.0.1")}</span>`,
    `<span class="meta-chip">Node ID: ${escapeHtml(node.node_id || "pending")}</span>`,
  ].join("");
}

async function loadPanelVersion() {
  try {
    const response = await fetch(getApiUrl("panel/version"));
    if (!response.ok) {
      return;
    }
    const payload = await response.json();
    if (payload && payload.panel_version && panelVersionBadge) {
      panelVersionBadge.textContent = payload.panel_version;
    }
  } catch (error) {
    console.error("Panel version load error:", error);
  }
}

function pollNodeTask(nodeId) {
  const interval = setInterval(async () => {
    try {
      const response = await fetch(getApiUrl(`api/v1/nodes/${nodeId}`));
      if (!response.ok) {
        return;
      }
      const data = await response.json();

      if (data.task_status === "success") {
        clearInterval(interval);
        updateNodeUsersState(`Node updated to ${data.node.node_version || "N0.0.1"}.`, "success");
        updateNodeBtn.disabled = false;
        await loadNodes();
        if (selectedNodeId === nodeId) {
          renderNodeMeta(data.node);
        }
      } else if (data.task_status === "failed") {
        clearInterval(interval);
        updateNodeUsersState(`Node update failed: ${data.task_log || "check logs"}`, "error");
        updateNodeBtn.disabled = false;
      }
    } catch (error) {
      console.error("Node task poll error:", error);
    }
  }, 2000);
}

async function updateSelectedNode() {
  const node = getSelectedNode();
  if (!node) {
    return;
  }

  if (!confirm(`Update node ${node.name} (${node.ip}) to current version?`)) {
    return;
  }

  const sshPassword = window.prompt(`Enter SSH password for root@${node.ip}:`);
  if (!sshPassword) {
    updateNodeUsersState("Update cancelled: SSH password is required.", "error");
    return;
  }

  updateNodeBtn.disabled = true;
  updateNodeUsersState(`Starting update on ${node.ip}...`);

  try {
    const response = await fetch(getApiUrl(`api/v1/nodes/${node.id}/update`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ssh_user: "root", ssh_password: sshPassword, ssh_port: 22 }),
    });

    if (!response.ok) {
      throw new Error(await parseErrorResponse(response));
    }

    const payload = await response.json();
    updateNodeUsersState(`Update task started (${payload.task_id}).`, "success");
    pollNodeTask(node.id);
  } catch (error) {
    updateNodeBtn.disabled = false;
    updateNodeUsersState(`Failed to start update: ${error.message}`, "error");
  }
}

function closeNodeDetailsModal() {
  nodeDetailsModal.classList.remove("open");
  selectedNodeId = null;
  nodeUsersList.innerHTML = "";
  nodeUserNameInput.value = "";
  updateNodeUsersState("Select a node to manage its users.");
  clearNodePreview();
}

function openNodeDetailsModal(node) {
  selectedNodeId = node.id;
  nodeDetailsModal.classList.add("open");
  nodeUserNameInput.value = "";
  nodeUsersList.innerHTML = "";
  renderNodeMeta(node);
  updateNodeUsersState(`Loading users from ${node.ip}...`);
  clearNodePreview();
}

function formatUserMeta(user) {
  const parts = [user.internal_ip || "No IP"];

  if (user.is_online) {
    parts.push("online");
  } else if (user.last_handshake) {
    parts.push(`last handshake: ${user.last_handshake}`);
  } else {
    parts.push("offline");
  }

  if (user.transfer_rx || user.transfer_tx) {
    parts.push(`RX ${user.transfer_rx || "0"} / TX ${user.transfer_tx || "0"}`);
  }

  return parts.join(" • ");
}

function renderNodeUsers(users) {
  if (!users.length) {
    nodeUsersList.innerHTML = '<div class="card empty-state"><p class="small">No users on this node yet.</p></div>';
    return;
  }

  nodeUsersList.innerHTML = users
    .map(
      (user) => `
        <div class="node-user-row" data-client-id="${escapeHtml(user.client_id)}" data-user-name="${escapeHtml(user.name)}">
          <div class="node-user-main">
            <h3 class="node-user-name">${escapeHtml(user.name)}</h3>
            <div class="node-user-meta">${escapeHtml(formatUserMeta(user))}</div>
          </div>
          <div class="node-user-actions">
            <button class="ghost" type="button" data-user-action="config">Config</button>
            <button class="ghost" type="button" data-user-action="qr">QR</button>
            <button class="danger" type="button" data-user-action="delete">Delete</button>
          </div>
        </div>
      `,
    )
    .join("");
}

async function loadNodeUsers(nodeId = selectedNodeId) {
  const node = nodeId ? nodesById.get(nodeId) : null;
  if (!node) {
    return;
  }

  refreshNodeUsersBtn.disabled = true;
  updateNodeUsersState(`Loading users from ${node.ip}...`);

  try {
    const response = await fetch(getApiUrlWithParams("panel/nodes", { target: node.ip }));
    if (!response.ok) {
      throw new Error(await parseErrorResponse(response));
    }

    const users = await response.json();
    if (selectedNodeId !== nodeId) {
      return;
    }

    renderNodeUsers(users);
    updateNodeUsersState(
      users.length ? `Loaded ${users.length} user${users.length === 1 ? "" : "s"}.` : "No users on this node yet.",
      users.length ? "success" : undefined,
    );
  } catch (error) {
    nodeUsersList.innerHTML = "";
    updateNodeUsersState(`Failed to load users: ${error.message}`, "error");
  } finally {
    refreshNodeUsersBtn.disabled = false;
  }
}

async function copyCode() {
  try {
    await navigator.clipboard.writeText(bootstrapCmd.textContent);
    alert("Command copied to clipboard!");
  } catch (error) {
    console.error("Copy failed:", error);
    alert("Failed to copy command");
  }
}

function selectNode(nodeId) {
  const node = nodesById.get(nodeId);
  if (!node) {
    return;
  }

  openNodeDetailsModal(node);
  loadNodeUsers(nodeId);
}

async function deleteNode(nodeId) {
  if (!confirm("Delete this node from the database?")) return;
  try {
    const response = await fetch(getApiUrl(`api/v1/nodes/${nodeId}`), { method: "DELETE" });
    if (response.ok || response.status === 204) {
      loadNodes();
    } else {
      const data = await response.json().catch(() => ({}));
      alert(`Error: ${data.detail || response.status}`);
    }
  } catch (error) {
    alert(`Error: ${error.message}`);
  }
}

function renderNodes(nodes) {
  nodesById = new Map(nodes.map((node) => [node.id, node]));

  if (selectedNodeId && !nodesById.has(selectedNodeId) && nodeDetailsModal.classList.contains("open")) {
    closeNodeDetailsModal();
  }

  if (selectedNodeId && nodesById.has(selectedNodeId) && nodeDetailsModal.classList.contains("open")) {
    renderNodeMeta(nodesById.get(selectedNodeId));
  }

  if (!nodes.length) {
    nodesGrid.innerHTML = emptyStateMarkup();
    return;
  }

  nodesGrid.innerHTML = nodes
    .map(
      (node) => `
        <div class="node-card" data-node-id="${node.id}">
          <div class="node-card-header">
            <div>
              <span class="node-status-light ${node.status === "active" ? "online" : "offline"}"></span>
              <span class="status-label">${escapeHtml(node.status)}</span>
            </div>
            <button class="node-delete-btn" title="Delete node" data-delete-id="${node.id}">×</button>
          </div>
          <div class="node-name">${escapeHtml(node.name)}</div>
          <div class="node-ip">${escapeHtml(node.ip)}</div>
          <p class="small">Version: ${escapeHtml(node.node_version || "N0.0.1")}</p>
          <p class="small">ID: ${escapeHtml(node.node_id || "pending")}</p>
        </div>
      `,
    )
    .join("");
}

function pollTaskStatus(nodeId) {
  const interval = setInterval(async () => {
    try {
      const response = await fetch(getApiUrl(`api/v1/nodes/${nodeId}`));
      if (!response.ok) {
        throw new Error(`Status ${response.status}`);
      }
      const data = await response.json();

      if (data.task_log) {
        installLog.textContent = data.task_log;
      }

      if (data.task_status === "success") {
        clearInterval(interval);
        setProgressMessage("Installation successful!", "success");
        installBtn.disabled = false;
      } else if (data.task_status === "failed") {
        clearInterval(interval);
        setProgressMessage("Installation failed. Check logs above.", "error");
        installBtn.disabled = false;
      }
    } catch (error) {
      console.error("Poll error:", error);
    }
  }, 2000);
}

function loadNodes() {
  fetch(getApiUrl("api/v1/nodes"))
    .then(async (response) => {
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || `HTTP ${response.status}`);
      }
      return response.json();
    })
    .then((nodes) => {
      renderNodes(nodes);
    })
    .catch((error) => console.error("Load nodes error:", error));
}

async function createNodeUser() {
  const node = getSelectedNode();
  const name = nodeUserNameInput.value.trim();

  if (!node) {
    return;
  }

  if (!name) {
    alert("Enter a user name");
    nodeUserNameInput.focus();
    return;
  }

  createNodeUserBtn.disabled = true;
  updateNodeUsersState(`Creating user on ${node.ip}...`);
  let timer;

  try {
    const controller = new AbortController();
    timer = setTimeout(() => controller.abort(), 30000);

    const response = await fetch(getApiUrlWithParams("panel/nodes", { target: node.ip }), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
      signal: controller.signal,
    });
    clearTimeout(timer);

    if (!response.ok) {
      throw new Error(await parseErrorResponse(response));
    }

    const payload = await response.json();
    if (!payload || !payload.user || !payload.user.client_id || typeof payload.config !== "string") {
      throw new Error("Unexpected create-user response from server");
    }

    const userKey = payload.user_key || payload.user.client_id;

    nodeUserNameInput.value = "";
    showConfigPreview(`${payload.user.name} config`, payload.config);
    updateNodeUsersState(`User ${payload.user.name} created. Key: ${userKey}`, "success");
    await loadNodeUsers(node.id);
  } catch (error) {
    if (error.name === "AbortError") {
      updateNodeUsersState("Failed to create user: request timeout (30s)", "error");
      return;
    }
    updateNodeUsersState(`Failed to create user: ${error.message}`, "error");
  } finally {
    if (timer) {
      clearTimeout(timer);
    }
    createNodeUserBtn.disabled = false;
  }
}

async function deleteNodeUser(clientId, userName) {
  const node = getSelectedNode();
  if (!node) {
    return;
  }

  if (!confirm(`Delete user ${userName}?`)) {
    return;
  }

  updateNodeUsersState(`Deleting ${userName}...`);

  try {
    const response = await fetch(getApiUrlWithParams(`panel/nodes/${encodeURIComponent(clientId)}`, { target: node.ip }), {
      method: "DELETE",
    });

    if (!response.ok && response.status !== 204) {
      throw new Error(await parseErrorResponse(response));
    }

    clearNodePreview();
    updateNodeUsersState(`User ${userName} deleted.`, "success");
    await loadNodeUsers(node.id);
  } catch (error) {
    updateNodeUsersState(`Failed to delete user: ${error.message}`, "error");
  }
}

async function showNodeUserConfig(clientId, userName) {
  const node = getSelectedNode();
  if (!node) {
    return;
  }

  updateNodeUsersState(`Loading config for ${userName}...`);

  try {
    const response = await fetch(getApiUrlWithParams(`panel/nodes/${encodeURIComponent(clientId)}/config`, { target: node.ip }));
    if (!response.ok) {
      throw new Error(await parseErrorResponse(response));
    }

    const configText = await response.text();
    showConfigPreview(`${userName} config`, configText);
    updateNodeUsersState(`Config loaded for ${userName}.`, "success");
  } catch (error) {
    updateNodeUsersState(`Failed to load config: ${error.message}`, "error");
  }
}

async function showNodeUserQr(clientId, userName) {
  const node = getSelectedNode();
  if (!node) {
    return;
  }

  updateNodeUsersState(`Loading QR for ${userName}...`);

  try {
    const response = await fetch(getApiUrlWithParams(`panel/nodes/${encodeURIComponent(clientId)}/qr`, { target: node.ip }));
    if (!response.ok) {
      throw new Error(await parseErrorResponse(response));
    }

    const blob = await response.blob();
    showQrPreview(`${userName} QR`, blob);
    updateNodeUsersState(`QR loaded for ${userName}.`, "success");
  } catch (error) {
    updateNodeUsersState(`Failed to load QR: ${error.message}`, "error");
  }
}

addNodeBtn.addEventListener("click", openModal);

modeAutoBtn.addEventListener("click", () => {
  currentMode = "auto";
  showStep("step2a", 66);
});

modeManualBtn.addEventListener("click", () => {
  currentMode = "manual";
  showStep("step2b", 66);
});

backBtn1.addEventListener("click", () => showStep("step1", 33));
backBtn2.addEventListener("click", () => showStep("step1", 33));

installBtn.addEventListener("click", async () => {
  const name = document.getElementById("nodeName").value.trim();
  const ip = document.getElementById("nodeIp").value.trim();
  const user = document.getElementById("sshUser").value.trim();
  const pass = document.getElementById("sshPassword").value;

  if (!name || !ip || !user || !pass) {
    alert("Fill in all SSH fields");
    return;
  }

  installBtn.disabled = true;
  showStep("step3", 100);
  setProgressMessage(`Installing on ${ip}...`);

  try {
    const response = await fetch(getApiUrl("api/v1/nodes/add"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: currentMode, name, ip, ssh_user: user, ssh_password: pass }),
    });

    const data = await response.json();
    if (response.ok && data.node_id) {
      pollTaskStatus(data.node_id);
    } else {
      setProgressMessage(`Error: ${data.detail || "Unknown error"}`, "error");
      installBtn.disabled = false;
    }
  } catch (error) {
    setProgressMessage(`Error: ${error.message}`, "error");
    installBtn.disabled = false;
  }
});

createBootstrapBtn.addEventListener("click", async () => {
  const name = document.getElementById("nodeNameManual").value.trim();
  const ip = document.getElementById("nodeIpManual").value.trim();

  if (!name || !ip) {
    alert("Fill in node name and IP");
    return;
  }

  createBootstrapBtn.disabled = true;

  try {
    const response = await fetch(getApiUrl("api/v1/nodes/add"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: currentMode, name, ip }),
    });

    const data = await response.json();
    if (response.ok && data.bootstrap_command) {
      bootstrapCmd.textContent = data.bootstrap_command;
      showStep("step3", 100);
      setProgressMessage("Bootstrap token created. Copy the command above and run it on your server.", "success");
      installLog.textContent = `Bootstrap Token:\n${data.bootstrap_command}`;
      closeModalBtn.disabled = false;
    } else {
      alert(`Error: ${data.detail || "Unknown"}`);
    }
  } catch (error) {
    alert(`Error: ${error.message}`);
  }

  createBootstrapBtn.disabled = false;
});

closeModalBtn.addEventListener("click", () => {
  closeAddNodeModal();
});

dismissAddNodeModalBtn.addEventListener("click", () => {
  closeAddNodeModal();
});

dismissNodeModalBtn.addEventListener("click", () => {
  closeNodeDetailsModal();
});

closeNodeModalBtn.addEventListener("click", () => {
  closeNodeDetailsModal();
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") {
    return;
  }

  if (qrModal.classList.contains("open")) {
    closeQrModal();
    return;
  }

  if (nodeDetailsModal.classList.contains("open")) {
    closeNodeDetailsModal();
    return;
  }

  if (modal.classList.contains("open")) {
    closeAddNodeModal();
  }
});

closeQrModalBtn.addEventListener("click", () => {
  closeQrModal();
});

qrModal.addEventListener("click", (event) => {
  if (event.target === qrModal) {
    closeQrModal();
  }
});

copyBootstrapBtn.addEventListener("click", copyCode);
createNodeUserBtn.addEventListener("click", createNodeUser);
refreshNodeUsersBtn.addEventListener("click", () => loadNodeUsers());
updateNodeBtn.addEventListener("click", updateSelectedNode);
clearNodePreviewBtn.addEventListener("click", clearNodePreview);
nodeUserNameInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    createNodeUser();
  }
});

nodeUsersList.addEventListener("click", (event) => {
  const actionButton = event.target.closest("[data-user-action]");
  if (!actionButton) {
    return;
  }

  const userRow = actionButton.closest("[data-client-id]");
  if (!userRow) {
    return;
  }

  const clientId = userRow.dataset.clientId;
  const userName = userRow.dataset.userName || clientId;
  const action = actionButton.dataset.userAction;

  if (action === "config") {
    showNodeUserConfig(clientId, userName);
    return;
  }

  if (action === "qr") {
    showNodeUserQr(clientId, userName);
    return;
  }

  if (action === "delete") {
    deleteNodeUser(clientId, userName);
  }
});

nodesGrid.addEventListener("click", (event) => {
  const deleteBtn = event.target.closest(".node-delete-btn");
  if (deleteBtn) {
    deleteNode(deleteBtn.dataset.deleteId);
    return;
  }
  const nodeCard = event.target.closest("[data-node-id]");
  if (nodeCard) {
    selectNode(nodeCard.dataset.nodeId);
  }
});

loadNodes();
loadPanelVersion();
setInterval(loadNodes, 10000);