import { RegistrationPanel } from "/registration.js";

const $ = (id) => document.getElementById(id);
const canvas = $("map"),
  ctx = canvas.getContext("2d");
const colors = { drivable: "#57d5a3", forbidden: "#f16e80" };
const titles = {
  pan: "浏览地图",
  drivable: "绘制可行驶区域",
  forbidden: "绘制禁行区域",
  waypoint: "添加航点",
  goal: "设置导航终点",
  obstacle: "添加仿真激光障碍",
  registration: "选择地图配准对应位置",
};
let registration,
  revision = null;
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
function action(fn) {
  return async () => {
    if (networkBusy) return;
    networkBusy = true;
    try {
      await fn();
    } catch (e) {
      notice(e.message, true);
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
function marker(x, y, color, label, yaw = 0) {
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
  ctx.rotate(project.map.origin[2] - yaw);
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(16, 0);
  ctx.lineTo(7, -4);
  ctx.lineTo(7, 4);
  ctx.fill();
  ctx.rotate(yaw - project.map.origin[2]);
  ctx.font = "11px sans-serif";
  ctx.fillStyle = color;
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
  if (
    runtime.path?.length &&
    ["规划完成", "导航中", "规划中", "正在接受目标", "已到达"].includes(runtime.navigation)
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
    marker(wp.x, wp.y, "#538bdf", `${i + 1} ${wp.name}`, wp.yaw),
  );
  if (goalSet) marker(goal.x, goal.y, "#d58a23", "终点", goal.yaw);
  if (runtime.pose)
    marker(
      runtime.pose.x,
      runtime.pose.y,
      "#169887",
      "小车 / 起点",
      runtime.pose.yaw,
    );
  for (const [x, y] of obstacles) marker(x, y, "#e45a60", "障碍");
  registration?.overlay(marker, polygon);
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
  $("dirty").textContent = "未保存";
  registration?.invalidate();
  renderLists();
  draw();
}
function setTool(value) {
  if (registration?.active && value !== "registration") registration.close();
  if (draft.length) notice("未完成的多边形已放弃");
  draft = [];
  tool = value;
  document
    .querySelectorAll("[data-tool]")
    .forEach((b) => b.classList.toggle("selected", b.dataset.tool === value));
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
    name.textContent = `${index + 1}. ${wp.name}`;
    const select = document.createElement("button");
    select.textContent = "选";
    select.title = "设为终点";
    select.onclick = () => {
      goal = { x: wp.x, y: wp.y, yaw: wp.yaw };
      goalSet = true;
      syncGoal();
      draw();
    };
    const edit = document.createElement("button");
    edit.textContent = "改";
    edit.title = "修改名称和航向";
    edit.onclick = () => {
      const text = prompt("航点名称", wp.name);
      if (text === null) return;
      const deg = prompt("航向（度）", String((wp.yaw * 180) / Math.PI));
      if (deg === null) return;
      const yaw = Number(deg);
      if (!Number.isFinite(yaw)) return notice("航向必须是有限数值", true);
      checkpoint();
      wp.name = text;
      wp.yaw = (yaw * Math.PI) / 180;
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
    del.title = "删除航点";
    del.onclick = () => {
      checkpoint();
      project.waypoints.splice(index, 1);
      changed();
    };
    row.append(name, select, edit, up, del);
    $("waypoints").append(row);
  });
  $("clearance").value = project.clearance_m;
}
function finishPolygon() {
  if (!["drivable", "forbidden"].includes(tool) || draft.length < 3)
    return notice("请至少选择三个顶点", true);
  checkpoint();
  project[tool].push(draft);
  draft = [];
  changed();
  notice("区域已添加，请保存并预览掩码");
}
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
  if (tool === "registration") {
    registration.select([x, y]);
  } else if (["drivable", "forbidden"].includes(tool)) {
    draft.push([x, y]);
    draw();
  } else if (tool === "waypoint") {
    checkpoint();
    project.waypoints.push({
      id: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()),
      name: `航点 ${project.waypoints.length + 1}`,
      x,
      y,
      yaw: goal.yaw,
    });
    changed();
  } else if (tool === "goal") {
    goal.x = x;
    goal.y = y;
    if (runtime.pose && Math.hypot(x - runtime.pose.x, y - runtime.pose.y) > 0.1)
      goal.yaw = Math.atan2(y - runtime.pose.y, x - runtime.pose.x);
    goalSet = true;
    syncGoal();
    notice("终点已设置；到达航向按起点至终点方向估算，可在右侧修改（0° 向东，90° 向北）");
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
  if (e.key === "Enter") finishPolygon();
  if (e.key === "Escape") {
    draft = [];
    draw();
  }
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
  $("goal-yaw").value = ((goal.yaw * 180) / Math.PI).toFixed(1);
}
for (const id of ["goal-x", "goal-y", "goal-yaw"])
  $(id).onchange = () => {
    goal = {
      x: Number($("goal-x").value),
      y: Number($("goal-y").value),
      yaw: (Number($("goal-yaw").value) * Math.PI) / 180,
    };
    goalSet =
      $("goal-x").value !== "" &&
      $("goal-y").value !== "" &&
      Object.values(goal).every(Number.isFinite);
    draw();
  };
async function save() {
  if (draft.length) throw new Error("请先完成或放弃当前多边形");
  const result = await api("/api/project", project);
  revision = result.revision;
  dirty = false;
  $("dirty").textContent = "已保存";
  renderStorage(result.storage);
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
    notice("请先点击“保存并预览导航掩码”");
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
  notice("已导出原始地图、标注项目和导航掩码");
});
$("apply").onclick = action(async () => {
  await save();
  await api("/api/apply", {});
  notice("已应用地图，请等待 Nav2 接收");
});
for (const [id, path, payload] of [
  ["plan", "plan", () => goal],
  ["navigate", "goal", () => goal],
  ["route", "route", () => ({ poses: project.waypoints })],
])
  $(id).onclick = action(async () => {
    if (dirty) throw new Error("地图有未保存修改，请先保存并应用");
    if (id !== "route" && !goalSet)
      throw new Error("请先在地图选择终点，或输入终点坐标");
    await api("/api/" + path, payload());
    notice(id === "plan" ? "已请求 Nav2 规划" : "已发送 Nav2 导航任务");
  });
$("cancel").onclick = async () => {
  try {
    await api("/api/cancel", {});
    notice("已请求取消，正在停止小车");
  } catch (e) {
    notice(e.message, true);
  }
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
  dirty = false;
  obstacles = [];
  goal = { x: 0, y: 0, yaw: 0 };
  goalSet = false;
  $("goal-x").value = "";
  $("goal-y").value = "";
  $("goal-yaw").value = "0";
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
    ? "请沿道路绘制可行驶区，建筑、水域等请设为禁行区。卫星图仅作标注底图，不会自动识别障碍。"
    : "绘制可行驶范围，再添加禁行区域。区域坐标以 map 米制坐标保存。";
  $("site-banner").textContent = project.map.site
    ? `${project.map.site.name} · ${project.map.site.address || ""} · ${project.map.site.basemap_type === "satellite" ? "真实卫星底图" : "真实地图"} · ${project.map.site.attribution || ""}`
    : "";
  if (project.map.georeference?.navigation_aligned === false) {
    $("map-info").textContent += "\n园区局部坐标 · 实车导航前需与定位配准";
  }
  const alignment = project.map.georeference?.registration;
  if (alignment) {
    $("map-info").textContent +=
      alignment.method === "geodetic_fromll"
        ? "\n经纬度自动对齐 · GPS 与影像实测精度待核对"
        : `\n${alignment.simulated ? "已配准 · 仅供仿真" : "已配准到 ROS map"} · 检查最大误差 ${Number.isFinite(alignment.check_max_m) ? alignment.check_max_m.toFixed(3) + " m" : "未记录"}`;
  }
  resize();
  fit();
  renderRuntime();
  registration?.reset(project, state.storage, state.map_id);
}
function renderStorage(storage) {
  if (!storage) return;
  $("storage-path").textContent =
    storage.snapshot_path || `尚未保存；数据目录：${storage.root}`;
}
function renderRuntime() {
  const ros = runtime.mode === "ros",
    connection = runtime.connection || {};
  $("connection").textContent = ros
    ? runtime.pose
      ? "ROS 2 · 定位已接收"
      : "ROS 2 · 等待定位"
    : "本地离线模式";
  $("nav-status").textContent = runtime.navigation || "服务未连接";
  $("nav-message").textContent = runtime.message || "";
  $("sensor-status").textContent = ros
    ? `底盘 ${runtime.chassis?.message || "待检查"} · ${runtime.odometry?.message || "里程计待检查"} · 激光 ${runtime.scan_age_s === null ? "未接收" : runtime.scan_age_s + " s"} · ${runtime.guard || "—"} · ${runtime.motion_enabled ? "运动已启用" : "仅规划"} · ${runtime.applied_revision ? "地图已应用" : "地图未应用"}`
    : "标注、保存和导出均可离线完成";
  $("start-pose").textContent = runtime.pose
    ? `X ${runtime.pose.x.toFixed(3)} m · Y ${runtime.pose.y.toFixed(3)} m\n朝向 ${((runtime.pose.yaw * 180) / Math.PI).toFixed(1)}° · map 坐标`
    : ros
      ? "尚无有效定位，请检查 map → base_link TF"
      : "离线编辑模式，请先连接 ROS";
  $("locate-start").disabled = !runtime.pose;
  $("ros-status").textContent = ros
    ? `${connection.simulated ? "模拟小车" : "实车接口"} · ROS_DOMAIN_ID=${connection.domain_id ?? "—"}\n定位 TF：${runtime.pose ? "已接收" : "未就绪 / 已过期"}\n激光 ${connection.scan_topic || "/scan"}：${runtime.scan_age_s === null ? "未接收有效数据" : runtime.scan_age_s + " s"}\nNav2 规划 / 导航 action：${connection.planner_ready ? "已发现" : "未发现"} / ${connection.navigator_ready ? "已发现" : "未发现"}\n速度输出：${runtime.motion_enabled ? "已启用" : "关闭，仅规划"}`
    : "当前为离线编辑模式，未启动 ROS 适配节点";
}
async function poll() {
  try {
    const state = await api("/api/state");
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
registration = new RegistrationPanel({
  api,
  action,
  notice,
  draw,
  setTool,
  loadState,
  project: () => project,
  revision: () => revision,
  runtime: () => runtime,
  saveIfNeeded: async () => {
    if (dirty || !revision) await save();
  },
});
new ResizeObserver(resize).observe(canvas);
window.addEventListener("beforeunload", (e) => {
  if (dirty) {
    e.preventDefault();
    e.returnValue = "";
  }
});
try {
  await loadState(await api("/api/state"));
  notice("地图已载入。选择左侧工具开始标注");
  poll();
} catch (e) {
  notice(e.message, true);
}
