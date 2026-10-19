
"use strict";

const $ = (id) => document.getElementById(id);

const csrfToken = () =>
  document.querySelector('meta[name="csrf-token"]')?.content || "";

let records = [];
let cameraStream = null;
let editingId = null;

// --------------------------------------------------
// API REQUEST HELPER — SENDS CSRF TOKEN AUTOMATICALLY
// --------------------------------------------------

async function apiRequest(url, options = {}) {
  const headers = new Headers(options.headers || {});
  const method = (options.method || "GET").toUpperCase();

  if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
    headers.set("X-CSRF-Token", csrfToken());
  }

  const response = await fetch(url, {
    ...options,
    method,
    headers,
    credentials: "same-origin"
  });

  const contentType = response.headers.get("content-type") || "";

  let data = {};

  if (contentType.includes("application/json")) {
    data = await response.json();
  }

  if (response.status === 401) {
    alert("Your session has expired. Please sign in again.");
    window.location.href = "/login";
    throw new Error("Login required");
  }

  if (!response.ok || data.success === false) {
    throw new Error(
      data.error || `Request failed (${response.status})`
    );
  }

  return data;
}

function showMessage(message, type = "info") {
  const target = $("app-message");

  if (target) {
    target.textContent = message;
    target.className = `notice ${type}`;
    target.hidden = false;

    return;
  }

  alert(message);
}

function escapeHTML(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  })[character]);
}

function formatMoney(value) {
  return "₹" + Number(value || 0).toLocaleString("en-IN", {
    maximumFractionDigits: 2
  });
}

// --------------------------------------------------
// UPDATE DASHBOARD TOTALS
// --------------------------------------------------

function updateTotals(stats = {}) {
  const values = {
    "vehicle-count": stats.vehicle_count ?? 0,
    "total-amount": formatMoney(stats.total_amount),
    "gpay-total": formatMoney(stats.gpay_total),
    "gpay-count": stats.gpay_count ?? 0,
    "phonepe-total": formatMoney(stats.phonepe_total),
    "phonepe-count": stats.phonepe_count ?? 0,
    "cash-total": formatMoney(stats.cash_total),
    "cash-count": stats.cash_count ?? 0
  };

  for (const [id, value] of Object.entries(values)) {
    const element = $(id);

    if (element) {
      element.textContent = value;
    }
  }
}

async function refreshTotals() {
  try {
    const data = await apiRequest("/api/totals");
    updateTotals(data.stats || data);
  } catch (error) {
    console.error("Could not refresh totals:", error.message);
  }
}

// --------------------------------------------------
// DISPLAY VEHICLE RECORDS
// --------------------------------------------------

function renderRecords() {
  const tbody = $("records-body");

  if (!tbody) return;

  const search = ($("search-input")?.value || "").trim().toLowerCase();

  const filtered = records.filter((record) => {
    return [
      record.vehicle_number,
      record.payment_method,
      record.created_at,
      record.amount
    ].some((value) =>
      String(value ?? "").toLowerCase().includes(search)
    );
  });

  if (!filtered.length) {
    tbody.innerHTML = `
      <tr>
        <td colspan="7" class="empty-state">
          No vehicle records found.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = filtered.map((record) => {
    const photoUrl = record.photo_url ||
      (record.photo_filename
        ? `/uploads/${encodeURIComponent(record.photo_filename)}`
        : "");

    const photo = photoUrl
      ? `<a href="${escapeHTML(photoUrl)}" target="_blank" rel="noopener">
           <img src="${escapeHTML(photoUrl)}"
                alt="Vehicle"
                class="vehicle-thumbnail"
                style="width:70px;height:48px;object-fit:cover;border-radius:8px">
         </a>`
      : "No photo";

    return `
      <tr data-id="${Number(record.id)}">
        <td>${Number(record.id)}</td>
        <td>${photo}</td>
        <td>${escapeHTML(record.vehicle_number || "Not detected")}</td>
        <td>${escapeHTML(formatMoney(record.amount))}</td>
        <td>${escapeHTML(record.payment_method)}</td>
        <td>${escapeHTML(record.created_at || "")}</td>
        <td>
          <button type="button" class="edit-record"
                  data-id="${Number(record.id)}">Edit</button>
          <button type="button" class="delete-record"
                  data-id="${Number(record.id)}">Delete</button>
        </td>
      </tr>
    `;
  }).join("");
}

async function loadRecords() {
  try {
    const data = await apiRequest("/api/vehicles");

    records = Array.isArray(data.records)
      ? data.records
      : Array.isArray(data.vehicles)
        ? data.vehicles
        : [];

    updateTotals(data.stats || data);
    renderRecords();
  } catch (error) {
    if (error.message !== "Login required") {
      showMessage(error.message, "error");
    }
  }
}

// --------------------------------------------------
// IMAGE PREVIEW
// --------------------------------------------------

function showImagePreview(file) {
  const preview = $("photo-preview");

  if (!preview || !file) return;

  const oldUrl = preview.dataset.objectUrl;

  if (oldUrl) {
    URL.revokeObjectURL(oldUrl);
  }

  const objectUrl = URL.createObjectURL(file);

  preview.dataset.objectUrl = objectUrl;
  preview.src = objectUrl;
  preview.hidden = false;
}

function selectedPhoto() {
  const input = $("photo-input");

  if (input?.files?.length) {
    return input.files[0];
  }

  return null;
}

// --------------------------------------------------
// SCAN NUMBER PLATE
// --------------------------------------------------

async function scanImage() {
  const file = selectedPhoto();

  if (!file) {
    showMessage("Please choose a vehicle image first.", "error");
    return;
  }

  const button = $("scan-button");
  const originalText = button?.textContent;

  try {
    if (button) {
      button.disabled = true;
      button.textContent = "Scanning...";
    }

    const formData = new FormData();
    formData.append("photo", file);

    const data = await apiRequest("/api/scan", {
      method: "POST",
      body: formData
    });

    const numberField = $("vehicle-number");

    if (numberField) {
      numberField.value = data.vehicle_number || "";
      numberField.dispatchEvent(new Event("input", { bubbles: true }));
      numberField.focus();
    }

    if (data.vehicle_number) {
      showMessage(
        `Detected number: ${data.vehicle_number}. Please verify it.`,
        "success"
      );
    } else {
      showMessage(
        data.message ||
          "No number detected. Try a clearer photo or enter it manually.",
        "error"
      );
    }
  } catch (error) {
    if (error.message !== "Login required") {
      showMessage(error.message, "error");
    }
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = originalText || "Scan";
    }
  }
}

// --------------------------------------------------
// SAVE A NEW VEHICLE
// --------------------------------------------------

async function saveVehicle(event) {
  event?.preventDefault();

  const numberField = $("vehicle-number");
  const amountField = $("amount");
  const paymentField = $("payment-method");
  const file = selectedPhoto();

  const vehicleNumber = (numberField?.value || "").trim();
  const amount = Number(amountField?.value || 0);
  const paymentMethod = paymentField?.value || "Cash";

  if (!file) {
    showMessage("Please select a vehicle photo.", "error");
    return;
  }

  if (amount < 0 || !Number.isFinite(amount)) {
    showMessage("Please enter a valid amount.", "error");
    return;
  }

  const button = $("save-button");
  const originalText = button?.textContent;

  try {
    if (button) {
      button.disabled = true;
      button.textContent = "Saving...";
    }

    const formData = new FormData();
    formData.append("photo", file);
    formData.append("vehicle_number", vehicleNumber);
    formData.append("amount", String(amount));
    formData.append("payment_method", paymentMethod);

    const data = await apiRequest("/api/vehicles", {
      method: "POST",
      body: formData
    });

    showMessage(
      data.vehicle_number
        ? `Vehicle saved: ${data.vehicle_number}`
        : "Vehicle saved. No plate number was detected; you can edit it.",
      "success"
    );

    if (numberField) numberField.value = "";
    if (amountField) amountField.value = "0";
    if ($("photo-input")) $("photo-input").value = "";

    const preview = $("photo-preview");

    if (preview) {
      if (preview.dataset.objectUrl) {
        URL.revokeObjectURL(preview.dataset.objectUrl);
      }

      preview.removeAttribute("src");
      preview.hidden = true;
      delete preview.dataset.objectUrl;
    }

    await loadRecords();
  } catch (error) {
    if (error.message !== "Login required") {
      showMessage(error.message, "error");
    }
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = originalText || "Save Vehicle";
    }
  }
}

// --------------------------------------------------
// EDIT A VEHICLE
// --------------------------------------------------

async function editVehicle(id) {
  const record = records.find((item) => Number(item.id) === Number(id));

  if (!record) {
    showMessage("Vehicle record not found.", "error");
    return;
  }

  const vehicleNumber = prompt(
    "Enter vehicle number:",
    record.vehicle_number || ""
  );

  if (vehicleNumber === null) return;

  const amountText = prompt(
    "Enter amount:",
    String(record.amount ?? 0)
  );

  if (amountText === null) return;

  const amount = Number(amountText);

  if (!Number.isFinite(amount) || amount < 0) {
    showMessage("Please enter a valid amount.", "error");
    return;
  }

  const paymentMethod = prompt(
    "Enter payment method: Google Pay, PhonePe, or Cash",
    record.payment_method || "Cash"
  );

  if (paymentMethod === null) return;

  const normalizedPayment = paymentMethod.trim().toLowerCase();
  const paymentMap = {
    "google pay": "Google Pay",
    "gpay": "Google Pay",
    "phonepe": "PhonePe",
    "cash": "Cash"
  };

  const finalPayment = paymentMap[normalizedPayment];

  if (!finalPayment) {
    showMessage("Use Google Pay, PhonePe, or Cash.", "error");
    return;
  }

  try {
    await apiRequest(`/api/vehicles/${Number(id)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        vehicle_number: vehicleNumber,
        amount,
        payment_method: finalPayment
      })
    });

    showMessage("Vehicle updated successfully.", "success");
    await loadRecords();
  } catch (error) {
    if (error.message !== "Login required") {
      showMessage(error.message, "error");
    }
  }
}

// --------------------------------------------------
// DELETE A VEHICLE
// --------------------------------------------------

async function deleteVehicle(id) {
  const record = records.find((item) => Number(item.id) === Number(id));

  if (!record) return;

  const confirmed = confirm(
    `Delete vehicle ${record.vehicle_number || record.id}?`
  );

  if (!confirmed) return;

  try {
    await apiRequest(`/api/vehicles/${Number(id)}`, {
      method: "DELETE"
    });

    showMessage("Vehicle deleted successfully.", "success");
    await loadRecords();
  } catch (error) {
    if (error.message !== "Login required") {
      showMessage(error.message, "error");
    }
  }
}

// --------------------------------------------------
// CAMERA SUPPORT
// --------------------------------------------------


async function startCamera() {
  const video = $("camera-video");

  if (!video) {
    showMessage("Camera preview is not present.", "error");
    return;
  }

  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "environment" },
      audio: false
    });

    video.srcObject = cameraStream;
    video.hidden = false;
    video.style.display = "block";
    video.style.visibility = "visible";
    video.style.width = "100%";
    video.style.maxWidth = "640px";
    video.style.height = "auto";

    await video.play();

    showMessage("Camera started successfully.", "success");
  } catch (error) {
    console.error("Camera error:", error);

    if (cameraStream) {
      cameraStream.getTracks().forEach(track => track.stop());
      cameraStream = null;
    }

    showMessage(
      "Could not open camera. Check browser permission.",
      "error"
    );
  }
}

function stopCamera() {
  if (cameraStream) {
    cameraStream.getTracks().forEach(track => track.stop());
    cameraStream = null;
  }

  const video = $("camera-video");

  if (video) {
    video.srcObject = null;
    video.hidden = true;
    video.style.display = "none";
  }
}


async function captureCameraPhoto() {
  const video = $("camera-video");

  if (!video || !video.videoWidth) {
    showMessage("Start the camera first.", "error");
    return;
  }

  const canvas = document.createElement("canvas");
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;

  const context = canvas.getContext("2d");
  context.drawImage(video, 0, 0, canvas.width, canvas.height);

  const blob = await new Promise((resolve) =>
    canvas.toBlob(resolve, "image/jpeg", 0.95)
  );

  if (!blob) {
    showMessage("Could not capture the photo.", "error");
    return;
  }

  const file = new File(
    [blob],
    `camera_${Date.now()}.jpg`,
    { type: "image/jpeg" }
  );

  const input = $("photo-input");

  if (input) {
    const transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
  }

  showImagePreview(file);
  stopCamera();
  showMessage("Photo captured. You can now scan it.", "success");
}

// --------------------------------------------------
// CSV EXPORT
// --------------------------------------------------

function exportCSV() {
  window.location.href = "/api/export.csv";
}
// ==================================================
// SHAMPOO SUPPLY REGISTER
// ==================================================

function supplyMessage(message, type = "info") {
  const target = $("supply-message");
  if (!target) return;

  target.textContent = message;
  target.className = `status-message ${type}`;
}

function localDateString() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function addSupplyItemRow(item = {}) {
  const tbody = $("supply-items-body");
  if (!tbody) return;

  const row = document.createElement("tr");

  row.innerHTML = `
    <td>
      <input class="supply-material" type="text"
             maxlength="150" placeholder="Shampoo name" required>
    </td>
    <td>
      <input class="supply-quantity" type="number"
             min="0.001" step="any" placeholder="Quantity" required>
    </td>
    <td>
      <select class="supply-unit">
        <option value="pieces">Pieces</option>
        <option value="litres">Litres</option>
      </select>
    </td>
    <td>
      <input class="supply-amount" type="number"
             min="0" max="1000000000" step="0.01"
             placeholder="Amount ₹" required>
    </td>
    <td>
      <button type="button" class="secondary remove-supply-item">
        Remove
      </button>
    </td>
  `;

  row.querySelector(".supply-material").value =
    item.material_name || "";
  row.querySelector(".supply-quantity").value =
    item.quantity ?? "";
  row.querySelector(".supply-unit").value =
    item.unit || "pieces";
  row.querySelector(".supply-amount").value =
    item.amount ?? "";

  tbody.appendChild(row);
  updateSupplyEntryTotal();
}

function updateSupplyEntryTotal() {
  const amounts = [
    ...document.querySelectorAll(".supply-amount")
  ];

  const total = amounts.reduce((sum, input) => {
    const value = Number(input.value);
    return sum + (Number.isFinite(value) && value >= 0 ? value : 0);
  }, 0);

  const target = $("supply-entry-total");
  if (target) target.textContent = formatMoney(total);
}

function collectSupplyItems() {
  const rows = [
    ...document.querySelectorAll("#supply-items-body tr")
  ];

  return rows.map((row) => ({
    material_name: row.querySelector(".supply-material").value.trim(),
    quantity: Number(row.querySelector(".supply-quantity").value),
    unit: row.querySelector(".supply-unit").value,
    amount: Number(row.querySelector(".supply-amount").value)
  }));
}

async function saveSupply(event) {
  event.preventDefault();

  const customerName = $("supply-customer").value.trim();
  const supplyDate = $("supply-date").value;
  const items = collectSupplyItems();

  if (!customerName || !supplyDate) {
    supplyMessage("Enter the washing centre name and supply date.", "error");
    return;
  }

  if (!items.length || items.some((item) =>
    !item.material_name ||
    !Number.isFinite(item.quantity) ||
    item.quantity <= 0 ||
    !Number.isFinite(item.amount) ||
    item.amount < 0 ||
    !["litres", "pieces"].includes(item.unit)
  )) {
    supplyMessage(
      "Check every material name, quantity, unit and amount.",
      "error"
    );
    return;
  }

  const button = $("save-supply");

  try {
    button.disabled = true;
    button.textContent = "Saving...";

    const data = await apiRequest("/api/supplies", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        customer_name: customerName,
        supply_date: supplyDate,
        items
      })
    });

    supplyMessage(
      `Supply saved for ${data.customer_name}. Entry total: ${formatMoney(data.total_amount)}.`,
      "success"
    );

    // Prepare a fresh, empty item row for the next supply.
$("supply-items-body").innerHTML = "";
addSupplyItemRow();

// Show the Add More Items button after saving.
const addMoreButton = document.getElementById("add-more-supply");

if (addMoreButton) {
    addMoreButton.hidden = false;
    addMoreButton.style.display = "inline-block";
}

await loadSupplyHistory();

  } catch (error) {
    if (error.message !== "Login required") {
      supplyMessage(error.message, "error");
    }
  } finally {
    button.disabled = false;
    button.textContent = "Save Shampoo Supply";
  }
}

async function loadSupplyHistory() {
  const target = $("supply-history");
  if (!target) return;

  const search = $("supply-search")?.value.trim() || "";
  target.textContent = "Loading supply history...";

  try {
    const data = await apiRequest(
      `/api/supplies?customer=${encodeURIComponent(search)}`
    );

    const centres = data.centres || [];

    if (!centres.length) {
      target.innerHTML =
        '<p class="muted">No matching washing centres found.</p>';
      return;
    }

    target.innerHTML = centres.map((centre) => {
      const entriesHTML = centre.entries.map((entry) => {
        const itemRows = entry.items.map((item) => `
          <tr>
            <td>${escapeHTML(item.material_name)}</td>
            <td>${escapeHTML(item.quantity)}</td>
            <td>${escapeHTML(item.unit)}</td>
            <td>${escapeHTML(formatMoney(item.amount))}</td>
          </tr>
        `).join("");

        return `
          <article class="stat-card" style="margin:12px 0">
<div style="display:flex; justify-content:space-between; align-items:center; gap:10px; flex-wrap:wrap;">
  <h3>Supply date: ${escapeHTML(entry.supply_date)}</h3>

  <div>
    <button type="button"
            class="edit-supply"
            data-id="${Number(entry.id)}">
      Edit
    </button>

    <button type="button"
            class="delete-supply"
            data-id="${Number(entry.id)}">
      Delete
    </button>
  </div>
</div>
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Material</th>
                    <th>Quantity</th>
                    <th>Unit</th>
                    <th>Amount</th>
                  </tr>
                </thead>
                <tbody>${itemRows}</tbody>
              </table>
            </div>
            <p>
              <strong>Entry total: ${escapeHTML(formatMoney(entry.total_amount))}</strong>
            </p>
          </article>
        `;
      }).join("");

      return `
        <section class="panel" style="margin-top:16px">
          <h3>${escapeHTML(centre.name)}</h3>
          <p>
            <strong>All-time recorded supply total:
              ${escapeHTML(formatMoney(centre.total_amount))}
            </strong>
          </p>
          ${entriesHTML || '<p class="muted">No supplies recorded yet.</p>'}
        </section>
      `;
    }).join("");
  } catch (error) {
    if (error.message !== "Login required") {
      target.textContent = error.message;
    }
  }
}

async function editSupply(id) {
  try {
    const data = await apiRequest(`/api/supplies/${Number(id)}`);
    const entry = data.entry;

    if (!entry) {
      supplyMessage("Supply entry not found.", "error");
      return;
    }

    const customer = prompt(
      "Washing centre name:",
      entry.customer_name || entry.centre_name || ""
    );
    if (customer === null) return;

    const date = prompt("Supply date (YYYY-MM-DD):", entry.supply_date || "");
    if (date === null) return;

    const items = entry.items || [];
    if (!items.length) {
      supplyMessage("No material details found for this entry.", "error");
      return;
    }

    const updatedItems = [];

    for (const item of items) {
      const name = prompt("Material name:", item.material_name || "");
      if (name === null) return;

      const quantityText = prompt("Quantity:", String(item.quantity ?? ""));
      if (quantityText === null) return;

      const amountText = prompt("Amount (₹):", String(item.amount ?? ""));
      if (amountText === null) return;

      updatedItems.push({
        material_name: name.trim(),
        quantity: Number(quantityText),
        unit: item.unit || "pieces",
        amount: Number(amountText)
      });
    }

    if (!customer.trim() || !date || updatedItems.some(item =>
      !item.material_name ||
      !Number.isFinite(item.quantity) || item.quantity <= 0 ||
      !Number.isFinite(item.amount) || item.amount < 0
    )) {
      supplyMessage("Please enter valid supply details.", "error");
      return;
    }

    await apiRequest(`/api/supplies/${Number(id)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        customer_name: customer.trim(),
        supply_date: date,
        items: updatedItems
      })
    });

    supplyMessage("Supply updated successfully.", "success");
    await loadSupplyHistory();
  } catch (error) {
    supplyMessage(error.message, "error");
  }
}

async function deleteSupply(id) {
  if (!confirm("Are you sure you want to delete this shampoo supply entry?")) {
    return;
  }

  try {
    await apiRequest(`/api/supplies/${Number(id)}`, {
      method: "DELETE"
    });

    supplyMessage("Supply deleted successfully.", "success");
    await loadSupplyHistory();
  } catch (error) {
    supplyMessage(error.message, "error");
  }
}


 // --------------------------------------------------
// CONNECT PAGE BUTTONS
// --------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  // Vehicle photo selection
  const photoInput = $("photo-input");

  photoInput?.addEventListener("change", () => {
    const file = selectedPhoto();

    if (file) {
      showImagePreview(file);
    }
  });

  // Supply form
  $("supply-form")?.addEventListener("submit", saveSupply);

  // Add another material
  $("add-supply-item")?.addEventListener("click", () => {
    addSupplyItemRow();
  });
// Show and connect Add More Items button
$("add-more-supply")?.addEventListener("click", () => {
  $("supply-items-body").innerHTML = "";
  addSupplyItemRow();

  $("add-more-supply").hidden = true;

  document.querySelector(".supply-material")?.focus();

  supplyMessage(
    "Enter the next shampoo or other materials, then save.",
    "info"
  );
});
  // Update total when amounts change
  $("supply-items-body")?.addEventListener("input", (event) => {
    if (event.target.classList.contains("supply-amount")) {
      updateSupplyEntryTotal();
    }
  });

  // Remove a material row
  $("supply-items-body")?.addEventListener("click", (event) => {
    if (event.target.closest(".remove-supply-item")) {
      const tbody = $("supply-items-body");
      const rows = tbody.querySelectorAll("tr");

      if (rows.length > 1) {
        event.target.closest("tr").remove();
        updateSupplyEntryTotal();
      }
    }
  });

  // Supply history search
  $("supply-search")?.addEventListener("input", loadSupplyHistory);

  // Load supply page
  if ($("supply-items-body")) {
    if ($("supply-date")) {
      $("supply-date").value = localDateString();
    }

    addSupplyItemRow();
    loadSupplyHistory();
  }

  
  // Edit and Delete supply buttons
  $("supply-history")?.addEventListener("click", (event) => {
    const editButton = event.target.closest(".edit-supply");
    const deleteButton = event.target.closest(".delete-supply");

    if (editButton) {
      editSupply(editButton.dataset.id);
    }

    if (deleteButton) {
      deleteSupply(deleteButton.dataset.id);
    }
  });

  // Vehicle controls
  $("scan-button")?.addEventListener("click", scanImage);
  $("save-button")?.addEventListener("click", saveVehicle);
  $("search-input")?.addEventListener("input", renderRecords);
  $("export-button")?.addEventListener("click", exportCSV);

  $("start-camera")?.addEventListener("click", startCamera);
  $("stop-camera")?.addEventListener("click", stopCamera);
  $("capture-camera")?.addEventListener("click", captureCameraPhoto);

  $("records-body")?.addEventListener("click", (event) => {
    const editButton = event.target.closest(".edit-record");
    const deleteButton = event.target.closest(".delete-record");

    if (editButton) {
      editVehicle(editButton.dataset.id);
    }

    if (deleteButton) {
      deleteVehicle(deleteButton.dataset.id);
    }
  });

  // Load vehicle records only on pages with the vehicle table
  if ($("records-body")) {
    // ---------------------------------------------
// SHAMPOO SUPPLY BUTTONS
// ---------------------------------------------

const supplyForm = $("supply-form");
const addItemButton = $("add-supply-item");
const addMoreButton = $("add-more-supply");
const supplySearch = $("supply-search");

// Save the supply form.
supplyForm?.addEventListener("submit", saveSupply);

// Add another material row before saving.
addItemButton?.addEventListener("click", () => {
    addSupplyItemRow();
});

// Add more items after a successful save.
addMoreButton?.addEventListener("click", () => {
    $("supply-items-body").innerHTML = "";

    addSupplyItemRow();

    addMoreButton.hidden = true;

    const firstMaterial = document.querySelector(".supply-material");

    firstMaterial?.focus();

    supplyMessage(
        "Add your next shampoo or other materials, then save.",
        "info"
    );
});

// Update the supply history search.
supplySearch?.addEventListener("input", loadSupplyHistory);

// Set today's date if the date field is empty.
const supplyDateInput = $("supply-date");

if (supplyDateInput && !supplyDateInput.value) {
    supplyDateInput.value = localDateString();
}

// Load saved supply history.
loadSupplyHistory();
    loadRecords();
  }
});
