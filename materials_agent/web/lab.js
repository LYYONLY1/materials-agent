const $ = id => document.getElementById(id);
const samples = {
  cu: ["Cu", 3.61],
  al: ["Al", 4.05],
  ni: ["Ni", 3.52],
};
const states = { queued: "等待计算", running: "计算中", succeeded: "计算完成", failed: "计算失败" };
const names = { energy: "单点能量", relaxation: "几何优化" };
const events = { queued: "进入队列", started: "工作进程开始计算", retry_scheduled: "已安排重试", succeeded: "结果已保存", failed: "任务失败" };
const date = new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
let viewer;
let previewVersion = 0;
let previewTimer;
let taskVersion = 0;
let taskId;
let result;
let initial;
let cell;
let stage = "initial";
let stream;
let submission;

async function api(path, body, key) {
  const headers = body ? { "Content-Type": "application/json" } : {};
  if (key) headers["Idempotency-Key"] = key;
  const response = await fetch(path, { method: body ? "POST" : "GET", headers, body: body && JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "请检查结构与计算参数");
  return data;
}

function fillSample() {
  const sample = samples[$("preset").value];
  if (!sample) {
    $("xyz").focus();
    return;
  }
  const [symbol, length] = sample;
  const half = length / 2;
  $("cell").value = length;
  $("xyz").value = [
    "4", symbol + " FCC",
    symbol + " 0.12 0.04 0.06",
    [symbol, 0, half, half].join(" "),
    [symbol, half, 0, half].join(" "),
    [symbol, half, half, 0].join(" "),
  ].join("\n");
  schedulePreview();
}

function drawingUnavailable() {
  $("viewer").textContent = "当前浏览器无法启用 WebGL。计算和结构下载仍可用。";
  $("reset").disabled = true;
}

function drawStructure(reset = false) {
  $("before").setAttribute("aria-pressed", String(stage === "initial"));
  $("after").setAttribute("aria-pressed", String(stage === "final"));
  $("after").disabled = !result;
  if (!viewer) return;
  const xyz = stage === "final" ? result?.structure_xyz : initial;
  viewer.removeAllModels();
  viewer.removeAllShapes();
  if (xyz) {
    viewer.addModel(xyz, "xyz");
    viewer.setStyle({}, { sphere: { scale: .39 }, stick: { radius: .13 } });
    const color = "#7caddc";
    for (const x of [0, cell]) {
      for (const y of [0, cell]) {
        viewer.addLine({ start: { x, y, z: 0 }, end: { x, y, z: cell }, color, dashed: true });
        viewer.addLine({ start: { x, y: 0, z: y }, end: { x, y: cell, z: y }, color, dashed: true });
        viewer.addLine({ start: { x: 0, y: x, z: y }, end: { x: cell, y: x, z: y }, color, dashed: true });
      }
    }
    if (reset) viewer.zoomTo();
  }
  viewer.render();
  $("reset").disabled = !xyz;
}

function values() {
  return { xyz: $("xyz").value, cell: Number($("cell").value) };
}

function schedulePreview() {
  clearTimeout(previewTimer);
  const version = ++previewVersion;
  if (taskId) {
    ++taskVersion;
    stream?.close();
    taskId = undefined;
    replaceTaskInUrl();
    showTask();
    loadHistory();
  }
  $("approved").checked = false;
  $("form-error").textContent = "";
  previewTimer = setTimeout(async () => {
    try {
      const data = values();
      const prepared = await api("/api/structures/preview", data);
      if (version !== previewVersion) return;
      initial = prepared.xyz;
      cell = data.cell;
      $("structure-info").textContent = prepared.formula + " · " + prepared.atom_count + " 个原子 · " + cell + " Å";
      drawStructure(true);
    } catch (error) {
      if (version !== previewVersion) return;
      initial = undefined;
      $("structure-info").textContent = error.message;
      drawStructure();
    }
  }, 180);
}

function replaceTaskInUrl() {
  const url = new URL(location.href);
  if (taskId) url.searchParams.set("experiment", taskId);
  else url.searchParams.delete("experiment");
  history.replaceState(null, "", url);
}

async function loadHistory() {
  try {
    const data = await api("/api/experiments");
    $("history-empty").hidden = data.experiments.length > 0;
    $("history-empty").textContent = "已提交的结构实验会保存在这里。";
    $("history").replaceChildren(...data.experiments.map(item => {
      const row = document.createElement("li");
      const link = document.createElement("a");
      link.href = "/?experiment=" + item.id;
      if (item.id === taskId) link.setAttribute("aria-current", "true");
      const label = document.createElement("span");
      label.textContent = item.material + " · " + names[item.calculation] + " · " + states[item.status];
      const time = document.createElement("time");
      const timestamp = new Date(item.created_at * 1000);
      time.dateTime = timestamp.toISOString();
      time.textContent = date.format(timestamp);
      link.append(label, time);
      row.append(link);
      link.addEventListener("click", event => {
        if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        openTask(item.id);
      });
      return row;
    }));
  } catch {
    $("history-empty").hidden = false;
    $("history-empty").textContent = "读取历史失败，请重试。";
  }
}

function metric(label, value) {
  const block = document.createElement("div");
  const term = document.createElement("dt");
  const reading = document.createElement("dd");
  term.textContent = label;
  reading.textContent = value;
  block.append(term, reading);
  return block;
}

function drawPlot(trajectory, threshold) {
  $("plot-box").hidden = trajectory.length < 2;
  if (trajectory.length < 2) return;
  const chart = $("plot");
  const { width, height } = chart;
  const context = chart.getContext("2d");
  const left = 55, right = width - 18, top = 14, bottom = height - 31;
  const largest = Math.max(threshold, ...trajectory.map(point => point.max_force_ev_per_angstrom));
  const y = value => bottom - value / largest * (bottom - top);
  const x = step => left + step / (trajectory.length - 1) * (right - left);
  context.clearRect(0, 0, width, height);
  const style = getComputedStyle(chart);
  context.font = "15px sans-serif";
  context.fillStyle = style.getPropertyValue("--muted").trim();
  context.strokeStyle = style.getPropertyValue("--border").trim();
  for (const value of [0, largest / 2, largest]) {
    context.beginPath();
    context.moveTo(left, y(value));
    context.lineTo(right, y(value));
    context.stroke();
    context.fillText(value.toFixed(2), 4, y(value) + 5);
  }
  context.fillText("0 步", left, height - 7);
  context.textAlign = "right";
  context.fillText((trajectory.length - 1) + " 步", right, height - 7);
  context.textAlign = "left";
  context.strokeStyle = style.getPropertyValue("--success").trim();
  context.setLineDash([6, 5]);
  context.beginPath();
  context.moveTo(left, y(threshold));
  context.lineTo(right, y(threshold));
  context.stroke();
  context.setLineDash([]);
  context.lineWidth = 3;
  context.strokeStyle = style.getPropertyValue("--accent").trim();
  context.beginPath();
  trajectory.forEach(point => context.lineTo(x(point.step), y(point.max_force_ev_per_angstrom)));
  context.stroke();
  context.lineWidth = 1;
  chart.setAttribute("aria-label", "最大受力从 " + trajectory[0].max_force_ev_per_angstrom.toFixed(4) +
    " 变为 " + trajectory.at(-1).max_force_ev_per_angstrom.toFixed(4) + " eV/Å，虚线为收敛阈值");
}

function showTask(task) {
  const state = task?.status;
  $("status").dataset.state = state || "";
  $("status").textContent = states[state] || "等待提交";
  $("timeline").hidden = !task;
  $("report").hidden = !task?.result;
  const next = task?.result;
  const sameResult = result?.structure_xyz === next?.structure_xyz;
  result = next;
  $("result-message").textContent = state === "failed" ? (task.error || "计算未完成")
    : state === "succeeded" ? (result.converged === null ? "单点能量计算 · ASE EMT"
      : (result.converged ? "已达到收敛阈值" : "达到迭代上限") + " · " + result.steps + " 步")
    : state ? "任务已提交，进度会自动更新。" : "提交实验后，这里会显示势能、最大受力和优化曲线。";
  $("events").replaceChildren(...(task?.events || []).map(event => {
    const row = document.createElement("li");
    row.textContent = events[event.event] || event.event;
    return row;
  }));
  if (!result) {
    stage = "initial";
    $("after").disabled = true;
    $("after").setAttribute("aria-pressed", "false");
    $("before").setAttribute("aria-pressed", "true");
    return;
  }
  initial = result.initial_structure_xyz;
  cell = result.cell_angstrom || task.parameters.structure?.cell;
  $("structure-info").textContent = result.material + " · " + result.atom_count + " 个原子 · " + cell + " Å";
  if (!sameResult) {
    stage = "final";
    drawStructure(true);
  }
  const change = (before, after, unit) => before.toFixed(4) + " → " + after.toFixed(4) + " " + unit;
  $("metrics").replaceChildren(
    metric("势能", change(result.initial_energy_ev, result.energy_ev, "eV")),
    metric("最大原子受力", change(result.initial_max_force_ev_per_angstrom, result.max_force_ev_per_angstrom, "eV/Å")),
  );
  drawPlot(result.trajectory, result.force_threshold_ev_per_angstrom);
  $("download-in").href = "/api/tasks/" + task.id + "/structure?stage=initial";
  $("download-out").href = "/api/tasks/" + task.id + "/structure";
}

async function openTask(id) {
  ++previewVersion;
  clearTimeout(previewTimer);
  const version = ++taskVersion;
  stream?.close();
  taskId = id;
  replaceTaskInUrl();
  showTask();
  let loadedParameters = false;

  async function snapshot() {
    const task = await api("/api/tasks/" + id);
    if (version !== taskVersion) return null;
    const structure = task.parameters.structure || (task.result?.initial_structure_xyz && {
      xyz: task.result.initial_structure_xyz,
      cell: task.result.cell_angstrom,
    });
    if (!structure) throw new Error("这条任务没有可用的三维结构。");
    if (!loadedParameters) {
      loadedParameters = true;
      $("preset").value = "custom";
      $("xyz").value = structure.xyz;
      $("cell").value = structure.cell;
      $("calculation").value = task.parameters.calculation;
      $("approved").checked = false;
      initial = structure.xyz;
      cell = structure.cell;
      stage = "initial";
      $("structure-info").textContent = task.parameters.material + " · " + cell + " Å";
      drawStructure(true);
    }
    showTask(task);
    return task;
  }

  async function poll() {
    if (version !== taskVersion) return;
    try {
      const task = await snapshot();
      if (!task) return;
      if (task.status === "running" || task.status === "queued") setTimeout(poll, 750);
      else loadHistory();
    } catch (error) {
      if (version === taskVersion) $("result-message").textContent = error.message;
    }
  }

  try {
    const task = await snapshot();
    if (!task) return;
    loadHistory();
    if (task.status !== "running" && task.status !== "queued") return;
    const source = new EventSource("/api/tasks/" + id + "/events?after=" + (task.events.at(-1)?.id ?? 0));
    stream = source;
    source.addEventListener("task_event", message => {
      if (version !== taskVersion) return;
      const event = JSON.parse(message.data);
      if (event.event !== "started" && event.event !== "retry_scheduled") return;
      const state = event.event === "started" ? "running" : "queued";
      $("status").dataset.state = state;
      $("status").textContent = states[state];
      const row = document.createElement("li");
      row.textContent = events[event.event];
      $("events").append(row);
    });
    function finishStream() {
      source.close();
      poll();
    }
    source.addEventListener("done", finishStream);
    source.onerror = finishStream;
  } catch (error) {
    if (version === taskVersion) $("result-message").textContent = error.message;
  }
}

$("experiment").addEventListener("submit", async event => {
  event.preventDefault();
  const body = { ...values(), calculation: $("calculation").value, approved: $("approved").checked };
  const fingerprint = JSON.stringify(body);
  if (submission?.fingerprint !== fingerprint) submission = { fingerprint, key: crypto.randomUUID() };
  $("submit").disabled = true;
  $("submit").textContent = "正在提交…";
  $("form-error").textContent = "";
  try {
    const data = await api("/api/experiments", body, submission.key);
    submission = undefined;
    await openTask(data.task_id);
  } catch (error) {
    $("form-error").textContent = error.message;
  } finally {
    $("submit").disabled = false;
    $("submit").textContent = "提交实验";
  }
});

$("import").onclick = () => $("file").click();
$("file").onchange = async () => {
  const file = $("file").files[0];
  $("file").value = "";
  if (!file) return;
  if (file.size > 16000) {
    $("form-error").textContent = "XYZ 文件需小于 16 KB。";
    return;
  }
  $("xyz").value = await file.text();
  $("preset").value = "custom";
  schedulePreview();
};
$("preset").onchange = fillSample;
$("xyz").oninput = () => { $("preset").value = "custom"; schedulePreview(); };
$("cell").oninput = () => { $("preset").value = "custom"; schedulePreview(); };
$("calculation").onchange = () => { $("approved").checked = false; };
$("reset").onclick = () => drawStructure(true);
$("before").onclick = () => { stage = "initial"; drawStructure(); };
$("after").onclick = () => { stage = "final"; drawStructure(); };
$("refresh").onclick = loadHistory;
$("download-csv").onclick = () => {
  const rows = result.trajectory.map(point => [point.step, point.energy_ev, point.max_force_ev_per_angstrom].join(","));
  const csv = ["step,energy_ev,max_force_ev_per_angstrom", ...rows].join("\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "optimization.csv";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if (result) drawPlot(result.trajectory, result.force_threshold_ev_per_angstrom);
});

try {
  viewer = window.$3Dmol.createViewer($("viewer"), { backgroundColor: "#192944" });
  if (!viewer) drawingUnavailable();
} catch {
  drawingUnavailable();
}
const opened = new URLSearchParams(location.search).get("experiment");
if (opened && /^[a-f0-9]{32}$/.test(opened)) openTask(opened);
else fillSample();
loadHistory();
