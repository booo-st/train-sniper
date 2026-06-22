const $ = (id) => document.getElementById(id);

let state = null;
let latestSearch = [];
let selected = new Set();
let lastSearchPayload = null;
let activeService = "ktx";
let profiles = [];

const KTX_STATIONS = [
  "서울", "용산", "영등포", "광명", "수원", "평택", "천안아산", "오송",
  "대전", "서대구", "김천구미", "동대구", "경주", "울산(통도사)", "부산",
  "포항", "광주송정", "나주", "목포", "익산", "전주", "남원", "순천",
  "여수EXPO", "마산", "창원중앙", "진주",
];

const SRT_STATIONS = [
  "수서", "동탄", "평택지제", "천안아산", "오송", "대전", "김천구미",
  "동대구", "신경주", "울산", "부산", "광주송정", "나주", "목포",
];

const SERVICE_META = {
  ktx: { label: "KTX", idLabel: "코레일 아이디", dep: "대전", arr: "서울", trainTypeDisabled: false },
  srt: { label: "SRT", idLabel: "SRT 아이디", dep: "수서", arr: "부산", trainTypeDisabled: true },
};

// ── Confirm modal ──────────────────────────────────────────
function showConfirm(message) {
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.innerHTML = `
      <div class="modal-box">
        <p class="modal-msg">${message}</p>
        <div class="button-row">
          <button class="btn-danger" id="confirmOk">삭제</button>
          <button id="confirmCancel">취소</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    overlay.querySelector("#confirmOk").onclick = () => { overlay.remove(); resolve(true); };
    overlay.querySelector("#confirmCancel").onclick = () => { overlay.remove(); resolve(false); };
    overlay.addEventListener("click", (e) => { if (e.target === overlay) { overlay.remove(); resolve(false); } });
  });
}

// ── Loading state ──────────────────────────────────────────
function setLoading(btn, loading) {
  if (!btn) return;
  btn.disabled = loading;
  if (loading) {
    btn.dataset.orig = btn.textContent;
    btn.textContent = "...";
  } else if (btn.dataset.orig) {
    btn.textContent = btn.dataset.orig;
    delete btn.dataset.orig;
  }
}

// ── Toast ──────────────────────────────────────────────────
function toast(message) {
  const el = $("toast");
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(window.__toastTimer);
  window.__toastTimer = setTimeout(() => el.classList.remove("show"), 3600);
}

// ── API ────────────────────────────────────────────────────
async function api(path, data = null) {
  const options = data
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) }
    : {};
  const res = await fetch(path, options);
  if (res.status === 401) { window.location.href = "/login"; return; }
  const json = await res.json();
  if (!json.ok) throw new Error(json.error || "요청 실패");
  return json;
}

// ── Helpers ────────────────────────────────────────────────
function compactTime(value) {
  if (!value) return "-";
  return `${value.slice(0, 2)}:${value.slice(2, 4)}`;
}

function compactDate(value) {
  if (!value || value.length !== 8) return value || "";
  return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
}

function today() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function currentTime() {
  const d = new Date();
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

// ── State & render ─────────────────────────────────────────
async function refresh() {
  state = await api("/api/state");
  renderSettings();
  renderJobs();
}

async function loadProfiles(service) {
  try {
    const res = await api(`/api/profiles?service=${service}`);
    profiles = res.profiles || [];
  } catch { profiles = []; }
  renderProfiles();
}

function renderProfiles() {
  const section = $("profileSection");
  const select = $("profileSelect");
  if (!profiles.length) { section.style.display = "none"; return; }
  section.style.display = "";
  select.innerHTML = profiles.map((p) => `<option value="${p.name}">${p.name} (${p.id})</option>`).join("");
}

async function applyProfile() {
  const name = $("profileSelect").value;
  if (!name) return;
  try {
    const res = await api("/api/profiles/apply", { service: activeService, name });
    state = { ...state, settings: res.settings };
    renderSettings();
    toast(`프로필 '${name}'을 적용했습니다.`);
  } catch (error) { toast(error.message); }
}

function populateStations(service) {
  const stations = service === "srt" ? SRT_STATIONS : KTX_STATIONS;
  const meta = SERVICE_META[service];
  ["dep", "arr"].forEach((id) => {
    const sel = $(id);
    if (!sel) return;
    const current = sel.value;
    sel.innerHTML = stations
      .map((s) => `<option value="${s}"${s === (current || meta[id]) ? " selected" : ""}>${s}</option>`)
      .join("");
    if (!current || !stations.includes(current)) sel.value = meta[id];
  });
}

function renderSettings() {
  const account = state.settings.accounts?.[activeService] || {};
  const meta = SERVICE_META[activeService];
  $("serviceLabel").textContent = meta.label;
  $("accountIdLabel").textContent = meta.idLabel;
  if (!isEditing("railId") && !isEditing("railPassword")) {
    $("railId").value = account.id || "";
  }
  if (!isEditing("telegramChat") && !isEditing("telegramToken")) {
    $("telegramChat").value = state.settings.telegram.chat_id || "";
  }
  $("sleepToggle").checked = Boolean(state.sleep_prevented);
  $("trainType").disabled = meta.trainTypeDisabled;
  if (activeService === "srt") $("trainType").value = "ktx";

  document.querySelectorAll(".tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.service === activeService);
  });

  $("accountStatus").textContent = account.id && account.has_password
    ? `${meta.label} · ${account.id}` : "계정 필요";
  $("accountStatus").className = `status-pill ${account.id && account.has_password ? "ok" : "warn"}`;

  $("telegramStatus").textContent = state.settings.telegram.has_token && state.settings.telegram.chat_id
    ? "텔레그램 연결됨" : "텔레그램 미연결";
  $("telegramStatus").className = `status-pill ${state.settings.telegram.has_token && state.settings.telegram.chat_id ? "ok" : "warn"}`;
}

function isEditing(id) {
  return document.activeElement === $(id);
}

// ── Train results ──────────────────────────────────────────
function renderResults() {
  const body = $("resultsBody");
  if (!latestSearch.length) {
    body.innerHTML = `<tr><td colspan="7" class="empty">조회 결과가 없습니다.</td></tr>`;
    $("resultCount").textContent = "0개";
    return;
  }
  $("resultCount").textContent = `${latestSearch.length}개 열차`;
  body.innerHTML = latestSearch.map((train) => {
    const isSelected = selected.has(train.train_no);
    const general = train.has_general_seat ? "yes" : "no";
    const special = train.has_special_seat ? "yes" : "no";
    const status = train.has_general_seat || train.has_special_seat
      ? "예약 가능" : train.has_waiting_list ? "예약대기" : "매진";
    return `
      <tr class="${isSelected ? "selected" : ""}" data-no="${train.train_no}">
        <td><input class="train-check" type="checkbox" data-no="${train.train_no}" ${isSelected ? "checked" : ""}></td>
        <td><strong>${train.train_type} ${train.train_no}</strong></td>
        <td>${compactDate(train.dep_date)} ${compactTime(train.dep_time)}</td>
        <td>${compactTime(train.arr_time)}</td>
        <td><span class="seat ${general}">${train.has_general_seat ? "가능" : "없음"}</span></td>
        <td><span class="seat ${special}">${train.has_special_seat ? "가능" : "없음"}</span></td>
        <td>${status}</td>
      </tr>`;
  }).join("");
}

// ── Job cards ──────────────────────────────────────────────
function renderJobCard(job) {
  const route = `${job.dep}→${job.arr} · ${compactDate(job.date)} ${compactTime(job.time)} 이후`;

  let progressHtml = "";
  if (job.active && job.next_check_in != null) {
    const pct = job.interval_max > 0 ? Math.round((job.next_check_in / job.interval_max) * 100) : 0;
    progressHtml = `
      <div class="progress-wrap">
        <div class="progress-fill" style="width:${pct}%"></div>
        <span class="countdown-text">${job.next_check_in}초 후 재조회</span>
      </div>`;
  }

  let actions = "";
  if (job.active) {
    actions = `
      <button data-action="stop" data-id="${job.id}">중지</button>
      <button data-action="delete" data-id="${job.id}" class="btn-danger">삭제</button>`;
  } else if (job.done) {
    actions = `
      <button data-action="start" data-id="${job.id}" class="primary">재개</button>
      <button data-action="delete" data-id="${job.id}" class="btn-danger">삭제</button>`;
  } else {
    actions = `
      <button data-action="start" data-id="${job.id}" class="primary">${job.started ? "재개" : "시작"}</button>
      <button data-action="delete" data-id="${job.id}" class="btn-danger">삭제</button>`;
  }

  const statusLabel = job.active ? "실행 중" : job.done ? "예약 완료" : "중지";
  const statusClass = job.active ? "ok" : job.done ? "ok" : "warn";

  return `
    <div class="job-card ${job.done ? "success" : ""}">
      <div class="job-top">
        <div>
          <div class="job-title">[${(job.service || "ktx").toUpperCase()}] ${job.name}</div>
          <div class="job-meta">${route}</div>
          <div class="job-meta">열차 ${job.train_numbers.join(", ")} · ${job.interval_min}–${job.interval_max}초</div>
        </div>
        <span class="status-pill ${statusClass}">${statusLabel}</span>
      </div>
      ${progressHtml}
      <div class="job-status">${job.result ? job.result.replaceAll("\n", "<br>") : job.last_status}</div>
      <div class="job-actions">${actions}</div>
      <div class="log-box">${job.logs.map((l) => `<div>${l}</div>`).join("") || "로그 없음"}</div>
    </div>`;
}

function renderJobs() {
  const list = $("jobsList");
  if (!state.jobs.length) {
    list.innerHTML = `<div class="empty-card">아직 작업이 없습니다.</div>`;
    return;
  }

  const running = state.jobs.filter((j) => j.active);
  const stopped = state.jobs.filter((j) => !j.active && !j.done);
  const done = state.jobs.filter((j) => j.done);

  const renderGroup = (title, jobs, cls) =>
    jobs.length
      ? `<div class="job-group ${cls}">
           <div class="job-group-title">${title} <span class="group-count">${jobs.length}</span></div>
           <div class="job-group-cards">${jobs.map(renderJobCard).join("")}</div>
         </div>`
      : "";

  list.innerHTML = [
    renderGroup("실행 중", running, "group-running"),
    renderGroup("중지됨", stopped, "group-stopped"),
    renderGroup("예약 완료", done, "group-done"),
  ].join("");
}

// ── Account ────────────────────────────────────────────────
async function submitAccount(event) {
  event.preventDefault();
  const btn = event.submitter;
  setLoading(btn, true);
  try {
    await api("/api/account", { service: activeService, id: $("railId").value, password: $("railPassword").value });
    $("railPassword").value = "";
    await refresh();
    toast("계정 정보를 저장했습니다.");
  } catch (error) { toast(error.message); }
  finally { setLoading(btn, false); }
}

async function testLogin() {
  const btn = $("testLoginBtn");
  setLoading(btn, true);
  try {
    const payload = $("railPassword").value
      ? { service: activeService, id: $("railId").value, password: $("railPassword").value }
      : { service: activeService };
    await api("/api/account/test", payload);
    toast("로그인 성공.");
  } catch (error) { toast(`로그인 실패: ${error.message}`); }
  finally { setLoading(btn, false); }
}

// ── Telegram ───────────────────────────────────────────────
async function submitTelegram(event) {
  event.preventDefault();
  const btn = event.submitter;
  setLoading(btn, true);
  try {
    await api("/api/telegram", { token: $("telegramToken").value, chat_id: $("telegramChat").value });
    $("telegramToken").value = "";
    await refresh();
    toast("텔레그램 정보를 저장했습니다.");
  } catch (error) { toast(error.message); }
  finally { setLoading(btn, false); }
}

async function testTelegram() {
  const btn = $("testTelegramBtn");
  setLoading(btn, true);
  try {
    const payload = {};
    if ($("telegramToken").value) payload.token = $("telegramToken").value;
    if ($("telegramChat").value) payload.chat_id = $("telegramChat").value;
    await api("/api/telegram/test", payload);
    toast("테스트 메시지를 보냈습니다.");
  } catch (error) { toast(`텔레그램 실패: ${error.message}`); }
  finally { setLoading(btn, false); }
}

// ── Search ─────────────────────────────────────────────────
async function submitSearch(event) {
  event.preventDefault();
  const btn = event.submitter;
  setLoading(btn, true);
  selected.clear();
  lastSearchPayload = {
    service: activeService,
    dep: $("dep").value,
    arr: $("arr").value,
    date: $("date").value,
    time: $("time").value,
    train_type: activeService === "srt" ? "srt" : $("trainType").value,
    adults: Number($("adults").value || 1),
    include_waiting: $("includeWaiting").checked,
  };
  try {
    $("resultCount").textContent = "조회 중...";
    const res = await api("/api/search", lastSearchPayload);
    latestSearch = res.trains;
    renderResults();
  } catch (error) {
    latestSearch = [];
    renderResults();
    toast(error.message);
  } finally { setLoading(btn, false); }
}

// ── Job creation ───────────────────────────────────────────
async function createJob(event) {
  event.preventDefault();
  if (!lastSearchPayload) { toast("먼저 열차를 조회하세요."); return; }
  if (!selected.size) { toast("감시할 열차를 선택하세요."); return; }

  const general = $("seatGeneral").checked;
  const special = $("seatSpecial").checked;
  if (!general && !special) { toast("좌석 유형을 하나 이상 선택하세요."); return; }
  const seat_option = general && special ? "general-first" : general ? "general-only" : "special-only";

  const btn = event.submitter;
  setLoading(btn, true);
  const payload = {
    ...lastSearchPayload,
    name: $("jobName").value.trim() || `${lastSearchPayload.dep}→${lastSearchPayload.arr}`,
    train_numbers: [...selected],
    interval_min: Number($("intervalMin").value),
    interval_max: Number($("intervalMax").value),
    seat_option,
    include_waiting: $("includeWaiting").checked,
  };
  try {
    const res = await api("/api/jobs", payload);
    await api(`/api/jobs/${res.job.id}/start`, {});
    await refresh();
    toast("스나이핑을 시작했습니다.");
  } catch (error) { toast(error.message); }
  finally { setLoading(btn, false); }
}

// ── Sleep ──────────────────────────────────────────────────
async function toggleSleep() {
  try {
    await api("/api/sleep", { prevent: $("sleepToggle").checked });
    await refresh();
    toast($("sleepToggle").checked ? "Mac 잠자기 방지를 켰습니다." : "Mac 잠자기 방지를 껐습니다.");
  } catch (error) {
    $("sleepToggle").checked = !$("sleepToggle").checked;
    toast(error.message);
  }
}

// ── Panel collapse ─────────────────────────────────────────
function togglePanel(panel) {
  panel.classList.toggle("collapsed");
  const btn = panel.querySelector(".panel-toggle");
  if (btn) btn.textContent = panel.classList.contains("collapsed") ? "▸" : "▾";
}

// ── Service tabs ───────────────────────────────────────────
function setService(service, clear = true) {
  activeService = service;
  populateStations(service);
  if (clear) {
    latestSearch = [];
    selected.clear();
    lastSearchPayload = null;
    $("jobName").value = "";
    renderResults();
  }
  const meta = SERVICE_META[service];
  if ($("trainType")) {
    $("trainType").disabled = meta.trainTypeDisabled;
    if (service === "srt") $("trainType").value = "ktx";
  }
  if (state) renderSettings();
  loadProfiles(service);
}

// ── Init ───────────────────────────────────────────────────
function bind() {
  $("date").value = today();
  $("time").value = currentTime();
  setService("ktx", false);

  $("accountForm").addEventListener("submit", submitAccount);
  $("telegramForm").addEventListener("submit", submitTelegram);
  $("searchForm").addEventListener("submit", submitSearch);
  $("jobForm").addEventListener("submit", createJob);
  $("testLoginBtn").addEventListener("click", testLogin);
  $("testTelegramBtn").addEventListener("click", testTelegram);
  $("refreshBtn").addEventListener("click", refresh);
  $("sleepToggle").addEventListener("change", toggleSleep);
  $("applyProfileBtn").addEventListener("click", applyProfile);

  $("selectAvailableBtn").addEventListener("click", () => {
    latestSearch.forEach((t) => {
      if (t.has_general_seat || t.has_special_seat) selected.add(t.train_no);
    });
    renderResults();
  });

  document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => setService(btn.dataset.service));
  });

  // Panel toggle buttons
  document.querySelectorAll(".panel-toggle").forEach((btn) => {
    btn.addEventListener("click", () => togglePanel(btn.closest(".panel")));
  });

  // Train row click (row = toggle, checkbox = its own change event)
  $("resultsBody").addEventListener("click", (e) => {
    if (e.target.classList.contains("train-check")) return;
    const row = e.target.closest("tr[data-no]");
    if (!row) return;
    const no = row.dataset.no;
    if (selected.has(no)) selected.delete(no);
    else selected.add(no);
    renderResults();
  });

  $("resultsBody").addEventListener("change", (e) => {
    if (!e.target.classList.contains("train-check")) return;
    const no = e.target.dataset.no;
    if (e.target.checked) selected.add(no);
    else selected.delete(no);
    renderResults();
  });

  // Job actions via event delegation
  $("jobsList").addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-action]");
    if (!btn || btn.disabled) return;
    const id = btn.dataset.id;
    const action = btn.dataset.action;
    if (action === "delete") {
      const ok = await showConfirm("이 작업을 삭제하시겠습니까?");
      if (!ok) return;
    }
    setLoading(btn, true);
    try {
      await api(`/api/jobs/${id}/${action}`, {});
      await refresh();
    } catch (error) { toast(error.message); }
  });
}

bind();
refresh().catch((error) => toast(error.message));
setInterval(() => refresh().catch(() => {}), 3000);
