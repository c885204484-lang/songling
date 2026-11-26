const $ = (id) => document.getElementById(id);
const canvas = $("map"),
  ctx = canvas.getContext("2d");
const speedButtons = document.querySelectorAll("[data-speed-kmh]");
let speedPending = false, speedError = "";
const colors = { drivable: "#57d5a3", forbidden: "#f16e80" };
const titles = {
  pan: "浏览地图",
  drivable: "绘制可行驶区域",
  forbidden: "绘制禁行区域",
  waypoint: "添加途径点",
  goal: "设置导航终点",
  obstacle: "添加仿真激光障碍",
};
let destinations = [null, null], editingDestination = 0;
let revision = null;
let project,
  runtime = {},
  baseImage,
  maskImage,
  tool = "pan",
  draft = [],
  history = [],
  dirty = false;
let view = { scale: 1, x: 0, y: 0 },
  pointer = null,
  moved = false,
  hover = null,
  obstacles = [];
let goal = { x: 0, y: 0, yaw: 0 },
  goalSet = false,
  networkBusy = false;
const clone = (value) => JSON.parse(JSON.stringify(value));
const waypointLabel = (name) => name.replace(/^航点(?= \d+$|$)/, "途径点");
function notice(message, error = false) {
  $("notice").textContent = message;
  $("notice").classList.toggle("error", error);
}
async function api(path, data) {
  const res = await fetch(
    path,
    data === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        },
  );
  const body = await res.json();
  if (!res.ok) throw new Error(body.error || `HTTP ${res.status}`);
  return body;
}
function action(fn, reportError = (error) => notice(error.message, true)) {
  return async () => {
    if (networkBusy) return;
    networkBusy = true;
    try {
      await fn();
    } catch (e) {
      reportError(e);
    } finally {
      networkBusy = false;
    }
  };
}
function worldToPixel([x, y]) {
  const [ox, oy, yaw] = project.map.origin,
    c = Math.cos(yaw),
    s = Math.sin(yaw),
    r = project.map.resolution;
  x -= ox;
  y -= oy;
  return [(c * x + s * y) / r, project.map.height - (-s * x + c * y) / r];
}
function pixelToWorld([x, y]) {
  const [ox, oy, yaw] = project.map.origin,
    r = project.map.resolution,
    c = Math.cos(yaw),
    s = Math.sin(yaw);
  x *= r;
  y = (project.map.height - y) * r;
  return [ox + c * x - s * y, oy + s * x + c * y];
}
function eventPixel(e) {
  const rect = canvas.getBoundingClientRect();
  return [
    (e.clientX - rect.left - view.x) / view.scale,
    (e.clientY - rect.top - view.y) / view.scale,
  ];
}
function inside([x, y]) {
  return x >= 0 && y >= 0 && x <= project.map.width && y <= project.map.height;
}
function resize() {
  const rect = canvas.getBoundingClientRect(),
    dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(rect.width * dpr);
  canvas.height = Math.round(rect.height * dpr);
  draw();
}
function fit() {
  if (!project) return;
  const rect = canvas.getBoundingClientRect();
  view.scale = Math.min(
    (rect.width - 60) / project.map.width,
    (rect.height - 60) / project.map.height,
  );
  view.x = (rect.width - project.map.width * view.scale) / 2;
  view.y = (rect.height - project.map.height * view.scale) / 2;
  draw();
}
function zoom(factor, centre) {
  const rect = canvas.getBoundingClientRect(),
    [cx, cy] = centre || [rect.width / 2, rect.height / 2],
    old = view.scale;
  view.scale = Math.max(0.015, Math.min(50, old * factor));
  view.x = cx - ((cx - view.x) * view.scale) / old;
  view.y = cy - ((cy - view.y) * view.scale) / old;
  draw();
}
function polygon(points, color, closed = true) {
  if (!points.length) return;
  ctx.beginPath();
  points.forEach((p, i) => {
    const [x, y] = worldToPixel(p);
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  if (closed) ctx.closePath();
  ctx.fillStyle = color + "32";
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.6 / view.scale;
  if (closed) ctx.fill();
  ctx.stroke();
}
function marker(x, y, color, label, yaw) {
  const [px, py] = worldToPixel([x, y]);
  ctx.save();
  ctx.translate(px, py);
  ctx.scale(1 / view.scale, 1 / view.scale);
  ctx.fillStyle = "#172534";
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.arc(0, 0, 9, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = color;
  if (Number.isFinite(yaw)) {
    ctx.rotate(project.map.origin[2] - yaw);
    ctx.beginPath();
    ctx.moveTo(9, 0);
    ctx.lineTo(27, 0);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(29, 0);
    ctx.lineTo(20, -5);
    ctx.lineTo(20, 5);
    ctx.fill();
    ctx.rotate(yaw - project.map.origin[2]);
    label += ` · ${(yaw * 180 / Math.PI).toFixed(0)}°`;
  }
  ctx.font = "11px sans-serif";
  ctx.fillText(label, 13, -12);
  ctx.restore();
}
function draw() {
  const dpr = window.devicePixelRatio || 1,
    w = canvas.width / dpr,
    h = canvas.height / dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = "#1e2b3a";
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let x = 0; x < w; x += 32) {
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
  }
  for (let y = 0; y < h; y += 32) {
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
  }
  ctx.stroke();
  if (!project || !baseImage) return;
  ctx.translate(view.x, view.y);
  ctx.scale(view.scale, view.scale);
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(baseImage, 0, 0, project.map.width, project.map.height);
  if (maskImage && $("show-mask").checked) ctx.drawImage(maskImage, 0, 0);
  for (const kind of ["drivable", "forbidden"])
    project[kind].forEach((p) => polygon(p, colors[kind]));
  if (draft.length) {
    polygon(draft, colors[tool] || "#fff", false);
    for (const p of draft) {
      const [x, y] = worldToPixel(p);
      ctx.fillStyle = colors[tool];
      ctx.beginPath();
      ctx.arc(x, y, 3 / view.scale, 0, Math.PI * 2);
      ctx.fill();
    }
    if (hover)
      polygon(
        [draft[draft.length - 1], pixelToWorld(hover)],
        colors[tool],
        false,
      );
  }
  const planned = !dirty && runtime.applied_revision === revision ? runtime.planned_targets || [] : [];
  const matches = (point, target) => target?.x === point.x && target?.y === point.y;
  const terminal = planned.at(-1);
  const goalMatches = goalSet && matches(goal, terminal);
  const routeMatches = goalMatches && planned.length === project.waypoints.length + 1 &&
    project.waypoints.every((wp, i) => matches(wp, planned[i]));
  const previewMatches = !runtime.planned_targets?.length || routeMatches || (planned.length === 1 && goalMatches);
  if (
    runtime.path?.length &&
    (runtime.navigation !== "规划完成" || previewMatches) &&
    ["规划完成", "导航中", "规划中", "正在接受目标", "已到达", "取消中", "任务失败", "已取消", "已暂停"].includes(runtime.navigation)
  ) polygon(runtime.path, "#448eff", false);
  ctx.fillStyle = "#efb044";
  for (const [x, y] of runtime.scan_points || []) {
    const p = worldToPixel([x, y]);
    ctx.fillRect(
      p[0] - 1.5 / view.scale,
      p[1] - 1.5 / view.scale,
      3 / view.scale,
      3 / view.scale,
    );
  }
  project.waypoints.forEach((wp, i) =>
    marker(wp.x, wp.y, "#538bdf", `${i + 1} ${waypointLabel(wp.name)}`, routeMatches ? planned[i].yaw : undefined),
  );
  if (goalSet) marker(goal.x, goal.y, "#d58a23", "终点", goalMatches ? terminal.yaw : undefined);
  if (runtime.pose)
    marker(
      runtime.pose.x,
      runtime.pose.y,
      "#169887",
      "小车 / 起点",
      runtime.pose.yaw,
    );
  for (const [x, y] of obstacles) marker(x, y, "#e45a60", "障碍");
  $("zoom").textContent = Math.round(view.scale * 100) + "%";
  $("scale-label").textContent =
    `1 px = ${project.map.resolution.toFixed(3)} m`;
}
function checkpoint() {
  history.push(clone(project));
  if (history.length > 50) history.shift();
}
function changed() {
  dirty = true;
  maskImage = null;
  $("show-mask").checked = false;
  $("dirty").textContent = "未保存";
  renderLists();
  draw();
}
function setTool(value) {
  if (value !== tool && draft.length) {
    draft = [];
    notice("未完成的多边形已放弃");
  } else if (Object.hasOwn(colors, value) && !draft.length) {
    notice("在地图上逐点标记，点击“完成多边形”结束");
  }
  tool = value;
  $("polygon-actions").hidden = !Object.hasOwn(colors, value);
  $("settings-dialog").close();
  $("mask-info-dialog").close();
  document
    .querySelectorAll("[data-tool]")
    .forEach((button) => {
      const selected = button.dataset.tool === value;
      button.classList.toggle("selected", selected);
      if (button.hasAttribute("aria-pressed")) button.setAttribute("aria-pressed", selected);
    });
  $("tool-title").textContent = titles[value];
  canvas.style.cursor = value === "pan" ? "grab" : "crosshair";
  draw();
}
function renderLists() {
  $("layers").replaceChildren();
  let count = 0;
  for (const kind of ["drivable", "forbidden"])
    project[kind].forEach((poly, index) => {
      count++;
      const row = document.createElement("div");
      row.className = "list-item";
      const label = document.createElement("span");
      label.textContent = `${kind === "drivable" ? "可行驶" : "禁行"} ${index + 1} · ${poly.length} 点`;
      label.style.color = colors[kind];
      const del = document.createElement("button");
      del.textContent = "删除";
      del.onclick = () => {
        checkpoint();
        project[kind].splice(index, 1);
        changed();
      };
      row.append(label, del);
      $("layers").append(row);
    });
  $("count").textContent = count + " 个";
  $("waypoint-count").textContent = project.waypoints.length + " 个";
  $("waypoints").replaceChildren();
  project.waypoints.forEach((wp, index) => {
    const row = document.createElement("div");
    row.className = "list-item";
    const name = document.createElement("span");
    name.textContent = `${index + 1}. ${waypointLabel(wp.name)}`;
    const select = document.createElement("button");
    select.textContent = "选";
    select.title = "设为终点";
    select.onclick = () => {
      goal = { x: wp.x, y: wp.y, yaw: wp.yaw };
      goalSet = true;
      syncGoal();
      $("task-dialog").close();
      draw();
    };
    const edit = document.createElement("button");
    edit.textContent = "改";
    edit.title = "修改途径点名称";
    edit.onclick = () => {
      const text = prompt("途径点名称", waypointLabel(wp.name));
      if (text === null) return;
      checkpoint();
      wp.name = text;
      changed();
    };
    const up = document.createElement("button");
    up.textContent = "↑";
    up.title = "前移";
    up.onclick = () => {
      if (index) {
        checkpoint();
        [project.waypoints[index - 1], project.waypoints[index]] = [
          wp,
          project.waypoints[index - 1],
        ];
        changed();
      }
    };
    const del = document.createElement("button");
    del.textContent = "×";
    del.title = "删除途径点";
    del.onclick = () => {
      checkpoint();
      project.waypoints.splice(index, 1);
      changed();
    };
    row.append(name, select, edit, up, del);
    $("waypoints").append(row);
  });
  renderWaypointCoordinates();
  $("clearance").value = project.clearance_m;
}
function finishPolygon() {
  if (!["drivable", "forbidden"].includes(tool) || draft.length < 3)
    return notice("请至少选择三个顶点", true);
  checkpoint();
  project[tool].push(draft);
  draft = [];
  changed();
  notice("区域已添加，点击右侧“应用地图”保存并启用");
}
const touches = new Map();
let pinch = null, multiTouch = false;
const touchGeometry = () => {
  const [a, b] = [...touches.values()];
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, d: Math.max(1, Math.hypot(a.x - b.x, a.y - b.y)) };
};
canvas.addEventListener("pointerdown", e => {
  if (e.pointerType !== "touch") return;
  touches.set(e.pointerId, {x: e.clientX, y: e.clientY});
  if (touches.size >= 2) {
    multiTouch = true;
    pointer = null;
    pinch = touchGeometry();
    canvas.setPointerCapture(e.pointerId);
    e.stopImmediatePropagation();
  }
});
canvas.addEventListener("pointermove", e => {
  if (!touches.has(e.pointerId)) return;
  touches.set(e.pointerId, {x: e.clientX, y: e.clientY});
  if (!multiTouch) return;
  e.stopImmediatePropagation();
  if (touches.size < 2) return;
  const next = touchGeometry(), r = canvas.getBoundingClientRect();
  zoom(next.d / pinch.d, [pinch.x - r.left, pinch.y - r.top]);
  view.x += next.x - pinch.x;
  view.y += next.y - pinch.y;
  pinch = next;
  draw();
});
for (const event of ["pointerup", "pointercancel"]) canvas.addEventListener(event, e => {
  touches.delete(e.pointerId);
  if (!multiTouch) return;
  e.stopImmediatePropagation();
  pointer = null;
  if (canvas.hasPointerCapture(e.pointerId)) canvas.releasePointerCapture(e.pointerId);
  if (!touches.size) { multiTouch = false; pinch = null; }
});
canvas.addEventListener("pointerdown", (e) => {
  if (!project) return;
  canvas.focus();
  pointer = {
    x: e.clientX,
    y: e.clientY,
    pan: tool === "pan" || e.button === 1,
  };
  moved = false;
  canvas.setPointerCapture(e.pointerId);
});
canvas.addEventListener("pointermove", (e) => {
  if (!project) return;
  const p = eventPixel(e);
  hover = p;
  const [x, y] = pixelToWorld(p);
  $("coords").textContent = `x ${x.toFixed(2)} m / y ${y.toFixed(2)} m`;
  if (pointer) {
    const dx = e.clientX - pointer.x,
      dy = e.clientY - pointer.y;
    if (Math.hypot(dx, dy) > 3) moved = true;
    if (pointer.pan) {
      view.x += dx;
      view.y += dy;
      pointer.x = e.clientX;
      pointer.y = e.clientY;
    }
  }
  draw();
});
canvas.addEventListener("pointerup", (e) => {
  if (!pointer) return;
  const wasPan = pointer.pan;
  pointer = null;
  canvas.releasePointerCapture(e.pointerId);
  if (wasPan || moved || !project) return;
  const p = eventPixel(e);
  if (!inside(p)) return notice("请在地图范围内选点", true);
  const [x, y] = pixelToWorld(p);
  if (["drivable", "forbidden"].includes(tool)) {
    draft.push([x, y]);
    draw();
  } else if (tool === "waypoint") {
    checkpoint();
    project.waypoints.push({
      id: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()),
      name: `途径点 ${project.waypoints.length + 1}`,
      x,
      y,
      yaw: 0,
    });
    changed();
  } else if (tool === "goal") {
    goal = { x, y, yaw: 0 };
    goalSet = true;
    syncGoal();
    notice("终点已设置，到达朝向由路径切线决定");
    draw();
  } else if (tool === "obstacle") {
    const next = [...obstacles, [x, y]];
    api("/api/obstacles", { points: next })
      .then(() => {
        obstacles = next;
        draw();
        notice("已添加仿真障碍");
      })
      .catch((e) => notice(e.message, true));
  }
});
canvas.addEventListener("pointercancel", () => {
  pointer = null;
});
canvas.addEventListener(
  "wheel",
  (e) => {
    e.preventDefault();
    const r = canvas.getBoundingClientRect();
    zoom(Math.exp(-e.deltaY * 0.001), [e.clientX - r.left, e.clientY - r.top]);
  },
  { passive: false },
);
document
  .querySelectorAll("[data-tool]")
  .forEach((button) => (button.onclick = () => setTool(button.dataset.tool)));
$("finish").onclick = finishPolygon;
$("discard-polygon").onclick = () => setTool("pan");
$("undo").onclick = () => {
  if (draft.length) {
    draft.pop();
    draw();
  } else if (history.length) {
    project = history.pop();
    changed();
  }
};
window.addEventListener("keydown", (e) => {
  if (["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName)) return;
  if (e.key === "Enter" && document.activeElement === canvas && Object.hasOwn(colors, tool))
    finishPolygon();
  if (e.key === "Escape" && draft.length && !document.querySelector("dialog[open]"))
    setTool("pan");
  if ((e.ctrlKey || e.metaKey) && e.key === "z") {
    e.preventDefault();
    $("undo").click();
  }
});
$("clearance").onchange = () => {
  const n = Number($("clearance").value);
  if (!Number.isFinite(n) || n < 0 || n > 5) {
    $("clearance").value = project.clearance_m;
    return notice("安全距离应在 0–5 米之间", true);
  }
  checkpoint();
  project.clearance_m = n;
  changed();
};
function syncGoal() {
  $("goal-x").value = goal.x.toFixed(3);
  $("goal-y").value = goal.y.toFixed(3);
  persistGoal();
  renderConsole();
}
for (const id of ["goal-x", "goal-y"])
  $(id).onchange = () => {
    goal = {
      x: Number($("goal-x").value),
      y: Number($("goal-y").value),
      yaw: 0,
    };
    goalSet =
      $("goal-x").value !== "" &&
      $("goal-y").value !== "" &&
      Object.values(goal).every(Number.isFinite);
    persistGoal();
    renderConsole();
    draw();
  };
async function save() {
  if (draft.length) throw new Error("请先完成或放弃当前多边形");
  if (goalSet) project.navigation_goal = { ...goal };
  const submitted = JSON.stringify(project);
  const result = await api("/api/project", project);
  revision = result.revision;
  persistGoal();
  dirty = JSON.stringify(project) !== submitted;
  $("dirty").textContent = dirty ? "未保存" : "已保存";
  renderStorage(result.storage);
  if (dirty || draft.length) throw new Error("保存期间地图又有修改，请完成编辑后重新保存");
  notice(`地图已保存到 ${result.storage.snapshot_path}`);
}
$("save").onclick = action(save);
$("mask").onclick = action(async () => {
  await save();
  maskImage = await loadImage("/api/mask.png?t=" + Date.now());
  $("show-mask").checked = true;
  draw();
});
$("show-mask").onchange = () => {
  if (!maskImage && $("show-mask").checked) {
    $("show-mask").checked = false;
    notice("请先点击“保存并预览通行范围”");
  }
  draw();
};
$("export").onclick = action(async () => {
  await save();
  const res = await fetch("/api/export");
  if (!res.ok) throw new Error("导出失败");
  const url = URL.createObjectURL(await res.blob()),
    link = document.createElement("a");
  link.href = url;
  link.download = "songling-offline-map.zip";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
  notice("已导出原始地图、标注项目和导航地图");
});
$("apply").onclick = action(async () => {
  await save();
  await api("/api/apply", {});
  notice("已应用地图，请等待 Nav2 接收");
});
function navigationPayload(direct = false) {
  if (runtime.mode === "ros" && !Array.isArray(runtime.planned_targets))
    throw new Error("请重启导航服务以加载自动朝向功能");
  const position = ({ x, y }) => ({ x, y });
  return !direct && project.waypoints.length
    ? { auto_heading: true, poses: [...project.waypoints, goal].map(position) }
    : { auto_heading: true, ...position(goal) };
}
function requireSavedMap() {
  if (draft.length) throw new Error("请先完成或放弃当前多边形");
  if (dirty) throw new Error("地图有未保存修改，请先点击右侧的“应用地图”");
}
for (const [id, direct] of [["plan", false], ["plan-route", true]])
  $(id).onclick = action(async () => {
    requireSavedMap();
    if (!goalSet)
      throw new Error("请先在地图选择终点，或输入终点坐标");
    if (!direct && project.waypoints.length >= 200)
      throw new Error("加上终点最多 200 个目标，请将中间途径点控制在 199 个以内");
    await api("/api/plan", navigationPayload(direct));
    if (direct) $("task-dialog").close();
    notice(direct ? "正在规划直接到终点的路径"
      : `正在规划经过 ${project.waypoints.length} 个途径点到达终点的路径`);
  });
let navigationChoice = null;
function navigationFeedback(message, error = false) {
  const feedback = $("navigation-feedback");
  feedback.textContent = message;
  feedback.classList.toggle("error", error);
  feedback.hidden = !message;
  if (message && !$("navigation-dialog").open) notice(message, error);
}

function navigationAction(submit) {
  return action(async () => {
    navigationFeedback("正在提交导航请求…");
    const message = await submit();
    $("navigation-dialog").close();
    notice(message);
  }, (error) => navigationFeedback(error.message, true));
}

function validateNavigationInput() {
  requireSavedMap();
  if (!goalSet) throw new Error("请先选择终点");
  if (project.waypoints.length >= 200) throw new Error("加上终点最多 200 个目标");
}
async function openNavigationChoices() {
  validateNavigationInput();
  const state = await api("/api/state");
  runtime = state.runtime;
  if (runtime.busy) throw new Error("已有任务正在执行，请先停止");
  if (state.revision !== revision) throw new Error("地图已更新，请刷新后再导航");
  navigationChoice = runtime.mission || { available: false };
  const m = navigationChoice, selector = $("resume-target");
  selector.replaceChildren();
  for (const [index, target] of (m.targets || []).entries()) {
    const option = document.createElement("option");
    option.value = index;
    option.textContent = `${index + 1}. ${waypointLabel(target.name)}`;
    selector.append(option);
  }
  selector.value = (m.progress_confirmed === false ? m.suggested_index : m.next_index) ?? 0;
  const resumable = m.available && m.compatible;
  $("resume-target-field").hidden = !resumable;
  $("mission-resume").disabled = !resumable;
  $("mission-resume").textContent = m.progress_confirmed === false
    ? "确认下一目标并继续任务" : "继续刚才的任务";
  $("mission-summary").textContent = m.available
    ? m.progress_confirmed === false
      ? "上次任务没有记录完成进度，请确认接下来要去的途径点。"
      : `上次任务已完成 ${m.completed} / ${m.total} 个目标，下一目标：${waypointLabel(m.next_name)}。`
    : "当前没有未完成的任务，可从头执行或直接到终点。";
  $("resume-help").textContent = resumable
    ? `继续使用原任务终点：X ${m.targets.at(-1).x.toFixed(2)} / Y ${m.targets.at(-1).y.toFixed(2)}。可在上方指定下一目标。`
    : m.unavailable_reason || "";
  $("mission-restart").textContent = project.waypoints.length
    ? "从途径点 1 重新执行全部任务" : "开始新的终点导航";
  $("navigation-dialog").showModal();
  const blocker = [runtime.chassis, runtime.odometry].find(sensor => sensor?.ready === false);
  navigationFeedback(blocker?.message || "", Boolean(blocker));
}
for (const id of ["navigate", "route"]) $(id).onclick = action(openNavigationChoices);
$("navigation-close").onclick = () => $("navigation-dialog").close();
$("mission-resume").onclick = navigationAction(async () => {
  validateNavigationInput();
  const m = navigationChoice;
  if (!m?.available || !m.compatible) throw new Error("没有可继续的任务");
  const payload = { task_id: m.task_id };
  const selected = Number($("resume-target").value);
  if (!m.progress_confirmed || selected !== m.next_index) payload.from_index = selected;
  await api("/api/resume", payload);
  return "已从当前位置继续剩余目标，直至终点";
});
$("mission-restart").onclick = navigationAction(async () => {
  validateNavigationInput();
  await api("/api/" + (project.waypoints.length ? "route" : "goal"), navigationPayload());
  return "正在准备导航，将按顺序经过全部途径点和终点";
});
$("mission-direct").onclick = navigationAction(async () => {
  validateNavigationInput();
  await api("/api/goal", navigationPayload(true));
  return "已请求从当前位置直接导航到终点";
});
async function stopNavigation() {
  try {
    await api("/api/cancel", {});
    notice("已请求取消，正在停止小车");
  } catch (e) {
    notice(e.message, true);
  }
}
$("cancel").onclick = stopNavigation;
$("speed-cancel").onclick = () => {
  $("speed-dialog").close();
  return stopNavigation();
};
$("clear-obstacles").onclick = action(async () => {
  await api("/api/obstacles", { points: [] });
  obstacles = [];
  draw();
  notice("已清除仿真障碍");
});
$("fit").onclick = fit;
$("zoom-in").onclick = () => zoom(1.25);
$("zoom-out").onclick = () => zoom(0.8);
$("import-open").onclick = () => $("import-dialog").showModal();
$("import-close").onclick = () => $("import-dialog").close();
$("ros-open").onclick = () => $("ros-dialog").showModal();
$("ros-close").onclick = () => $("ros-dialog").close();
$("locate-start").onclick = action(async () => {
  runtime = (await api("/api/state")).runtime;
  renderRuntime();
  if (!runtime.pose)
    throw new Error("未收到有效定位，请先连接 ROS 并检查 map → base_link TF");
  const p = worldToPixel([runtime.pose.x, runtime.pose.y]);
  if (!inside(p))
    throw new Error("小车定位在地图范围之外，请检查地图与定位坐标是否一致");
  const rect = canvas.getBoundingClientRect();
  view.x = rect.width / 2 - p[0] * view.scale;
  view.y = rect.height / 2 - p[1] * view.scale;
  draw();
  notice("当前实时定位作为导航起点；设置终点后即可请求规划");
});
function base64(buffer) {
  let text = "";
  const bytes = new Uint8Array(buffer);
  for (let i = 0; i < bytes.length; i += 8192)
    text += String.fromCharCode(...bytes.subarray(i, i + 8192));
  return btoa(text);
}
$("import-form").onsubmit = async (e) => {
  e.preventDefault();
  if (networkBusy) return;
  networkBusy = true;
  try {
    const file = $("project-file").files[0],
      payload = {
        yaml: await $("yaml-file").files[0].text(),
        image: base64(await $("image-file").files[0].arrayBuffer()),
      };
    if (file) payload.project = JSON.parse(await file.text());
    const basemap = $("basemap-file").files[0];
    if (basemap) payload.basemap = base64(await basemap.arrayBuffer());
    const state = await api("/api/import", payload);
    await loadState(state);
    $("import-dialog").close();
    notice("地图已导入并保存，请绘制区域后应用");
  } catch (e) {
    notice(e.message, true);
  } finally {
    networkBusy = false;
  }
};
async function loadImage(url) {
  const image = new Image();
  image.src = url;
  await image.decode();
  return image;
}
async function loadState(state) {
  project = state.project;
  revision = state.revision;
  runtime = state.runtime;
  history = [];
  draft = [];
  maskImage = null;
  $("show-mask").checked = false;
  dirty = false;
  obstacles = [];
  goal = { x: 0, y: 0, yaw: 0 };
  goalSet = false;
  $("goal-x").value = "";
  $("goal-y").value = "";
  restoreGoal();
  $("dirty").textContent = "已保存";
  renderStorage(state.storage);
  baseImage = await loadImage("/api/map.png?t=" + Date.now());
  renderLists();
  $("map-info").textContent =
    `${project.map.site?.name ? project.map.site.name + "\n" + project.map.site.address + "\n" : ""}${project.map.width} × ${project.map.height} 栅格 · ${project.map.resolution.toFixed(3)} m/px\n原点 ${project.map.origin.map((n) => n.toFixed(2)).join(", ")}${project.map.site?.attribution ? "\n" + project.map.site.attribution : ""}`;
  $("map-label").textContent = project.map.site
    ? "园区实景 · 离线底图"
    : "MAP / 米制坐标";
  $("site-banner").hidden = !project.map.site;
  $("annotation-hint").textContent = project.map.has_basemap
    ? "请沿道路绘制可行驶区域，圈外及禁行区禁止通行。卫星底图仅供标注参考。"
    : "仅可行驶区域内允许通行，禁行区优先。区域坐标以 map 米制坐标保存。";
  $("site-banner").textContent = project.map.site
    ? `${project.map.site.name} · ${project.map.site.address || ""} · ${project.map.site.basemap_type === "satellite" ? "真实卫星底图" : "真实地图"} · ${project.map.site.attribution || ""}`
    : "";
  if (project.map.georeference?.navigation_aligned === false) {
    $("map-info").textContent += "\n园区局部坐标 · 实车导航前需与定位配准";
  }
  resize();
  fit();
  renderRuntime();
  loadDestinations();
}
function renderStorage(storage) {
  if (!storage) return;
  $("storage-path").textContent =
    storage.snapshot_path || `尚未保存；数据目录：${storage.root}`;
}
function renderRuntime() {
  renderConsole();
  renderSpeed();
  const ros = runtime.mode === "ros",
    connection = runtime.connection || {};
  $("connection").textContent = ros
    ? runtime.pose
      ? (connection.lidar_enabled === false ? "ROS 2 · 无雷达 · 定位已接收" : "ROS 2 · 定位已接收")
      : "ROS 2 · 等待定位"
    : "本地离线模式";
  $("nav-status").textContent = runtime.navigation || "服务未连接";
  $("nav-message").textContent = runtime.message || "";
  $("sensor-status").textContent = ros
    ? `底盘 ${runtime.chassis?.message || "待检查"} · ${runtime.odometry?.message || "里程计待检查"} · ${runtime.connection?.lidar_enabled === false ? "无雷达模式 · 按地图行驶" : "激光 " + (runtime.scan_age_s === null ? "未接收" : runtime.scan_age_s + " s")} · ${runtime.guard || "—"} · ${runtime.motion_enabled ? "运动已启用" : "仅规划"} · ${runtime.applied_revision ? "地图已应用" : "地图未应用"}`
    : "标注、保存和导出均可离线完成";
  $("start-pose").textContent = runtime.pose
    ? `X ${runtime.pose.x.toFixed(3)} m · Y ${runtime.pose.y.toFixed(3)} m\n朝向 ${((runtime.pose.yaw * 180) / Math.PI).toFixed(1)}° · map 坐标`
    : ros
      ? "尚无有效定位，请检查 map → base_link TF"
      : "离线编辑模式，请先连接 ROS";
  $("locate-start").disabled = !runtime.pose;
  $("ros-status").textContent = ros
    ? `${connection.simulated ? "模拟小车" : "实车接口"} · ROS_DOMAIN_ID=${connection.domain_id ?? "—"}\n定位 TF：${runtime.pose ? "已接收" : "未就绪 / 已过期"}\n${connection.lidar_enabled === false ? "无雷达模式：按地图行驶，不检测临时障碍物" : "激光 " + (connection.scan_topic || "/scan") + "：" + (runtime.scan_age_s === null ? "未接收有效数据" : runtime.scan_age_s + " s")}\nNav2 规划 / 导航 action：${connection.planner_ready ? "已发现" : "未发现"} / ${connection.navigator_ready ? "已发现" : "未发现"}\n速度输出：${runtime.motion_enabled ? "已启用" : "关闭，仅规划"}`
    : "当前为离线编辑模式，未启动 ROS 适配节点";
}
function renderSpeed() {
  const connected = runtime.mode === "ros";
  $("speed-cancel").hidden = !runtime.busy;
  for (const button of speedButtons) {
    button.disabled = !connected || speedPending;
    button.setAttribute("aria-pressed", Number(button.dataset.speedKmh) === runtime.speed_gear_kmh);
  }
  $("speed-status").textContent = speedError || (speedPending ? "正在切换档位…" :
    !connected ? "连接 ROS 后可调节速度" :
    runtime.speed_gear_kmh ? `当前档位 ${runtime.speed_gear_kmh} km/h` : "当前使用默认巡航速度");
}

for (const button of speedButtons) {
  button.onclick = async () => {
    speedPending = true;
    speedError = "";
    renderSpeed();
    try {
      const result = await api("/api/speed", { kmh: Number(button.dataset.speedKmh) });
      runtime.speed_gear_kmh = result.speed_gear_kmh;
    } catch (error) {
      speedError = error.message;
    } finally {
      speedPending = false;
      renderSpeed();
    }
  };
}

async function poll() {
  try {
    const requestedRevision = revision;
    const state = await api("/api/state");
    if (!networkBusy && !dirty && !draft.length && revision === requestedRevision && state.revision !== revision) {
      const sameMap = JSON.stringify(project?.map) === JSON.stringify(state.project.map);
      const retainedView = sameMap ? { ...view } : null;
      await loadState(state);
      if (retainedView) view = retainedView;
      notice("地图与途径点设置已同步更新");
    }
    runtime = state.runtime;
    renderStorage(state.storage);
    renderRuntime();
    draw();
  } catch (e) {
    runtime = {};
    renderRuntime();
    $("start-pose").textContent = "服务已断开，实时起点不可用";
    $("ros-status").textContent = "网页服务已断开，请检查服务进程";
    $("connection").textContent = "服务已断开";
    draw();
    notice(e.message, true);
  } finally {
    setTimeout(poll, 700);
  }
}
new ResizeObserver(resize).observe(canvas);
window.addEventListener("beforeunload", (e) => {
  if (dirty) {
    e.preventDefault();
    e.returnValue = "";
  }
});
try {
  await loadState(await api("/api/state"));
  notice(project.drivable.length
    ? "地图已载入。选择终点后规划路径，确认后开始导航"
    : "请先绘制可行驶区域，再点击“应用地图”");
  poll();
} catch (e) {
  notice(e.message, true);
}

// Keep the console uncluttered; the full editor remains available in dialogs.
for (const name of ["settings", "mask-info", "speed", "task", "destination"]) {
  $(name + "-close").onclick = () => $(name + "-dialog").close();
}
$("settings-open").onclick = () => $("settings-dialog").showModal();
$("mask-info-open").onclick = () => $("mask-info-dialog").showModal();
$("speed-open").onclick = () => $("speed-dialog").showModal();
$("task-open").onclick = () => $("task-dialog").showModal();
function renderWaypointCoordinates() {
  const host = $("waypoint-coordinates");
  host.replaceChildren();
  project.waypoints.forEach((wp, index) => {
    const row = document.createElement("div");
    const title = document.createElement("span");
    title.textContent = `${index + 1}. ${waypointLabel(wp.name)}`;
    const coordinates = document.createElement("div");
    coordinates.className = "target-grid";
    for (const axis of ["x", "y"]) {
      const field = document.createElement("label");
      field.textContent = `${axis.toUpperCase()} / m`;
      const coordinate = document.createElement("input");
      coordinate.type = "number";
      coordinate.step = "0.1";
      coordinate.value = wp[axis].toFixed(3);
      coordinate.setAttribute("aria-label", `${waypointLabel(wp.name)} ${axis.toUpperCase()} 坐标（米）`);
      coordinate.onchange = () => {
        const value = Number(coordinate.value);
        const position = { ...wp, [axis]: value };
        if (!coordinate.value.trim() || !Number.isFinite(value) || !inside(worldToPixel([position.x, position.y]))) {
          coordinate.value = wp[axis].toFixed(3);
          return notice("途径点坐标必须在地图范围内", true);
        }
        checkpoint();
        wp[axis] = value;
        changed();
      };
      field.append(coordinate);
      coordinates.append(field);
    }
    row.append(title, coordinates);
    host.append(row);
  });
}
function destinationStorageKey() {
  return "songling-destinations-v1:" + JSON.stringify(project.map);
}
function goalStorageKey() {
  return "songling-goal-v1:" + JSON.stringify(project.map);
}
function persistGoal() {
  if (!project || !goalSet || !Object.values(goal).every(Number.isFinite)) return;
  try { localStorage.setItem(goalStorageKey(), JSON.stringify({ ...goal, revision })); } catch {}
}
function restoreGoal() {
  try {
    let saved = JSON.parse(localStorage.getItem(goalStorageKey()));
    if (project.navigation_goal && saved?.revision !== revision)
      saved = project.navigation_goal;
    if (!saved || ![saved.x, saved.y, saved.yaw].every(Number.isFinite) || !inside(worldToPixel([saved.x, saved.y]))) return;
    goal = { x: saved.x, y: saved.y, yaw: saved.yaw };
    goalSet = true;
    syncGoal();
  } catch {}
}
function validDestination(p) {
  return p && typeof p.name === "string" && p.name.trim() &&
    [p.x, p.y].every(Number.isFinite) && inside(worldToPixel([p.x, p.y]));
}
function loadDestinations() {
  try {
    const saved = JSON.parse(localStorage.getItem(destinationStorageKey()));
    destinations = [0, 1].map(i => validDestination(saved?.[i]) ? saved[i] : null);
  } catch { destinations = [null, null]; }
  renderDestinations();
}
function renderDestinations() {
  destinations.forEach((p, i) => {
    $("destination-" + i).textContent = `导航到「${p?.name || (i ? "点位二" : "点位一")}」`;
    $("destination-" + i).title = p ? `仅规划 · X ${p.x.toFixed(2)} / Y ${p.y.toFixed(2)}` : "请先设置名称和位置";
  });
}
function editDestination(i) {
  editingDestination = i;
  const p = destinations[i];
  $("destination-name").value = p?.name || (i ? "点位二" : "点位一");
  $("destination-x").value = p?.x ?? "";
  $("destination-y").value = p?.y ?? "";
  $("destination-dialog").showModal();
}
document.querySelectorAll("[data-edit-destination]").forEach(b => {
  b.onclick = () => editDestination(Number(b.dataset.editDestination));
});
$("destination-use-goal").onclick = () => {
  if (!goalSet) return notice("请先在地图选择终点", true);
  $("destination-x").value = goal.x;
  $("destination-y").value = goal.y;
};
$("destination-form").onsubmit = e => {
  e.preventDefault();
  const p = { name: $("destination-name").value.trim(),
    x: Number($("destination-x").value), y: Number($("destination-y").value) };
  if (!validDestination(p)) return notice("请输入名称及地图范围内的有效坐标", true);
  const next = [...destinations];
  next[editingDestination] = p;
  try { localStorage.setItem(destinationStorageKey(), JSON.stringify(next)); }
  catch { return notice("浏览器无法保存点位，请检查存储权限", true); }
  destinations = next;
  renderDestinations();
  $("destination-dialog").close();
  notice(`已保存快捷目的地「${p.name}」`);
};
for (let i = 0; i < 2; i++) $("destination-" + i).onclick = action(async () => {
  const p = destinations[i];
  if (!p) return editDestination(i);
  goal = { x: p.x, y: p.y, yaw: 0 };
  goalSet = true;
  syncGoal();
  draw();
  renderConsole();
  requireSavedMap();
  if (project.waypoints.length >= 200) throw new Error("加上终点最多 200 个目标");
  await api("/api/plan", navigationPayload());
  notice(`正在规划：依次经过 ${project.waypoints.length} 个途径点 →「${p.name}」；点击“开始导航”后行驶`);
});
function renderConsole() {
  const chassis = runtime.chassis || {}, simulated = runtime.connection?.simulated;
  const wheelMissing = runtime.wheel_odometry?.required && runtime.wheel_odometry.ready === false;
  const fresh = Number.isFinite(chassis.age_s) && chassis.age_s <= 1;
  const status = (id, text, ok) => {
    $(id).textContent = text;
    $(id).className = ok ? "ok" : "warn";
  };
  status("can-status", simulated ? "CAN：仿真" : fresh ? "CAN：反馈正常" : "CAN：无有效反馈", fresh || simulated);
  status("rc-status", simulated ? "遥控档位：仿真" : !fresh ? "遥控档位：未知" : chassis.control_mode === 1 ? "遥控档位：自动 / CAN" : "遥控档位：未到自动", simulated || (fresh && chassis.control_mode === 1));
  status("pose-status", runtime.pose ? wheelMissing ? "定位已接收 / 底盘反馈中断" : "定位：正常" : "定位：未就绪", !!runtime.pose && !wheelMissing);
  status("motion-status", wheelMissing ? "运动：等待底盘反馈" : runtime.motion_enabled ? "运动：已启用" : "运动：仅规划", !!runtime.motion_enabled && !wheelMissing);
  $("compact-status").textContent = runtime.navigation || "服务未连接";
  $("compact-message").textContent = runtime.message || "";
  $("compact-message").hidden = !runtime.message;
  if (wheelMissing) {
    $("compact-message").textContent = runtime.wheel_odometry.message;
    $("compact-message").hidden = false;
  }
  $("compact-status").title = [runtime.message, chassis.message, runtime.guard].filter(Boolean).join(" · ");
  $("compact-pose").textContent = runtime.pose ? `小车 X ${runtime.pose.x.toFixed(2)} / Y ${runtime.pose.y.toFixed(2)} m · 车头 ${(runtime.pose.yaw * 180 / Math.PI).toFixed(1)}°` : "小车：等待实时定位";
  $("compact-goal").textContent = goalSet ? `终点 X ${goal.x.toFixed(2)} / Y ${goal.y.toFixed(2)} m` : "终点：点击地图选取";
  $("compact-route").textContent = "路线：当前位置 → " +
    (project?.waypoints || []).map((wp, i) => `${i + 1}. ${waypointLabel(wp.name)}`).concat(goalSet ? "橙色终点" : "请选择终点").join(" → ");
}
loadDestinations();
renderConsole();

