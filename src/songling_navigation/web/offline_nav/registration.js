const $ = (id) => document.getElementById(id);

export class RegistrationPanel {
  constructor(host) {
    this.host = host;
    this.points = [];
    this.selected = null;
    this.report = null;
    this.active = false;
    this.pending = false;
    this.perform = (fn) =>
      host.action(async () => {
        this.pending = true;
        $("registration-fields").disabled = true;
        try {
          await fn();
        } finally {
          this.pending = false;
          $("registration-fields").disabled = false;
        }
      });
    $("registration-open").onclick = host.action(async () => {
      if (host.runtime().busy)
        throw new Error("请先取消规划或导航，再配准地图");
      await host.saveIfNeeded();
      this.active = true;
      $("registration-panel").hidden = false;
      $("navigation-panel").hidden = true;
      this.pick();
      $("registration-panel").scrollIntoView({ block: "nearest" });
    });
    $("registration-close").onclick = () => this.close();
    $("registration-geodetic").onclick = this.perform(async () => {
      await host.saveIfNeeded();
      const state = await host.api("/api/registration/save", {
        revision: host.revision(), project: host.project(), method: "geodetic_fromll",
      });
      this.close();
      await host.loadState(state);
      host.notice("已按经纬度自动对齐并另存；请重新应用地图，核对现场位置。GPS 漂移仍会影响精度。");
    });
    $("registration-pick").onclick = () => this.pick();
    $("registration-capture").onclick = this.perform(async () => {
      this.requireSelected();
      const sample = await host.api("/api/registration/pose", {});
      this.add(sample);
    });
    $("registration-manual").onclick = this.perform(async () => {
      this.requireSelected();
      const inputs = [$("registration-x"), $("registration-y")];
      if (
        inputs.some(
          (input) =>
            input.value.trim() === "" || !Number.isFinite(Number(input.value)),
        )
      )
        throw new Error("请填写有效的 ROS map X、Y 坐标");
      this.add({
        robot: inputs.map((input) => Number(input.value)),
        source: "manual",
        captured_at: new Date().toISOString(),
        simulated: host.runtime().connection?.simulated === true,
      });
    });
    $("registration-clear").onclick = () => {
      if (
        this.points.length &&
        !confirm("清空本次配准对应点？已保存地图不受影响。")
      )
        return;
      this.points = [];
      this.selected = null;
      this.invalidate();
      this.render();
    };
    for (const id of ["registration-scale", "registration-tolerance"])
      $(id).onchange = () => this.invalidate();
    $("registration-fixed").onchange = () => this.refreshSave();
    $("registration-preview").onclick = this.perform(async () => {
      this.report = null;
      this.refreshSave();
      try {
        await host.saveIfNeeded();
        this.report = await host.api(
          "/api/registration/preview",
          this.payload(),
        );
        this.renderReport();
        this.render();
      } catch (error) {
        $("registration-report").textContent = error.message;
        $("registration-report").classList.add("error");
        this.render();
        throw error;
      }
    });
    $("registration-save").onclick = this.perform(async () => {
      if (!this.report?.passed || !$("registration-fixed").checked)
        throw new Error("请先通过误差检查，并确认定位坐标系已固定");
      const state = await host.api("/api/registration/save", this.payload());
      this.points = [];
      this.persist();
      this.close();
      await host.loadState(state);
      host.notice(
        `配准地图已另存到 ${state.storage.snapshot_path}；请重新应用到 Nav2${state.project.map.georeference.registration.simulated ? "（仅供仿真）" : ""}`,
      );
    });
  }

  reset(project, storage, mapId) {
    this.close();
    this.points = [];
    this.selected = null;
    this.report = null;
    $("registration-fixed").checked = false;
    const map = project.map;
    this.key =
      "songling-registration:" +
      JSON.stringify([
        storage?.root,
        mapId,
        map.width,
        map.height,
        map.resolution,
        map.origin,
      ]);
    try {
      const saved = JSON.parse(localStorage.getItem(this.key));
      if (saved && Array.isArray(saved.points) && saved.points.length <= 30) {
        this.points = saved.points.filter(
          (point) =>
            point &&
            ["map", "robot"].every(
              (key) =>
                Array.isArray(point[key]) &&
                point[key].length === 2 &&
                point[key].every(Number.isFinite),
            ) &&
            ["fit", "check"].includes(point.role) &&
            typeof point.name === "string",
        );
        $("registration-scale").checked = saved.fit_scale === true;
        $("registration-tolerance").value = saved.max_error_m ?? 0.75;
      }
    } catch {
      /* Storage is optional; the server still validates every point. */
    }
    this.invalidate();
    this.render();
  }

  payload() {
    return {
      revision: this.host.revision(),
      project: this.host.project(),
      points: this.points,
      fit_scale: $("registration-scale").checked,
      max_error_m: Number($("registration-tolerance").value),
      fixed_frame_confirmed: $("registration-fixed").checked,
    };
  }

  persist() {
    if (!this.key) return;
    try {
      localStorage.setItem(
        this.key,
        JSON.stringify({
          points: this.points,
          fit_scale: $("registration-scale").checked,
          max_error_m: Number($("registration-tolerance").value),
        }),
      );
    } catch {
      /* Private browsing and full storage do not prevent registration. */
    }
  }

  invalidate() {
    this.report = null;
    $("registration-report").textContent =
      "点位或参数已更新，请计算配准与检查误差。";
    $("registration-report").classList.remove("error");
    this.refreshSave();
    this.persist();
    this.host.draw();
  }

  refreshSave() {
    $("registration-save").disabled = !(
      this.report?.passed && $("registration-fixed").checked
    );
  }

  pick() {
    this.host.setTool("registration");
    this.host.notice("点击卫星图上小车所在的地面位置，再读取当前小车坐标");
  }

  select(point) {
    if (this.pending) return;
    this.selected = point;
    this.render();
    this.host.notice(
      "地图位置已选中；停稳小车后读取当前位置，或输入已记录的 ROS 坐标",
    );
  }

  requireSelected() {
    if (!this.selected) throw new Error("请先在地图上选择对应位置");
    if (this.points.length >= 30) throw new Error("最多保存 30 个对应点");
  }

  add(sample) {
    this.points.push({
      ...sample,
      map: [...this.selected],
      name:
        "P" +
        (Math.max(0, ...this.points.map((p) => Number(p.name.slice(1)) || 0)) +
          1),
      role: "fit",
    });
    this.selected = null;
    $("registration-x").value = "";
    $("registration-y").value = "";
    this.invalidate();
    this.render();
    this.host.notice(
      "对应点已添加，请继续选择下一个位置；至少保留一个独立检查点",
    );
  }

  render() {
    const gps = this.host.runtime().gps;
    $("registration-gps").textContent = gps
      ? `GPS ${gps.status === 0 ? "普通定位" : "增强定位"} · 水平标准差 ${Number.isFinite(gps.horizontal_sigma_m) ? gps.horizontal_sigma_m.toFixed(2) + " m" : "未知"}`
      : "尚无实时 GPS 精度数据";
    $("registration-geodetic").disabled =
      this.host.project().map.georeference?.source_crs !== "GCJ-02" ||
      !!this.host.project().map.georeference?.registration;
    $("registration-selected").textContent = this.selected
      ? `已选地图位置：${this.selected.map((v) => v.toFixed(3)).join(", ")} m`
      : "请在地图选择下一个对应位置";
    $("registration-points").replaceChildren();
    this.points.forEach((point, index) => {
      const row = document.createElement("div");
      row.className = "registration-point";
      const text = document.createElement("div");
      const error = this.report?.points[index]?.error_m;
      text.textContent = `${point.name} · ${point.source === "ros" ? (point.simulated ? "仿真采集" : "ROS 采集") : "手工坐标"}\n图 ${point.map.map((v) => Number(v).toFixed(2)).join(", ")}\n车 ${point.robot.map((v) => Number(v).toFixed(2)).join(", ")}${error === undefined ? "" : `\n误差 ${error.toFixed(3)} m`}`;
      const remove = document.createElement("button");
      remove.textContent = "删除";
      remove.onclick = () => {
        this.points.splice(index, 1);
        this.invalidate();
        this.render();
      };
      const role = document.createElement("label");
      role.className = "check";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = point.role === "check";
      checkbox.onchange = () => {
        point.role = checkbox.checked ? "check" : "fit";
        this.invalidate();
        this.render();
      };
      role.append(checkbox, "独立检查点（不参与拟合）");
      row.append(text, remove, role);
      $("registration-points").append(row);
    });
    this.host.draw();
  }

  renderReport() {
    const r = this.report;
    $("registration-report").textContent =
      `配准 ${r.fit_count} 点 · 检查 ${r.check_count} 点\n拟合 RMS ${r.fit_rms_m.toFixed(3)} m\n配准最大误差 ${r.fit_max_m.toFixed(3)} m\n检查最大误差 ${r.check_max_m === null ? "缺少独立检查点" : r.check_max_m.toFixed(3) + " m"}\n旋转 ${((r.yaw * 180) / Math.PI).toFixed(3)}°\n平移 ${r.translation.map((v) => v.toFixed(3)).join(", ")} m\n采用比例 ${r.scale.toFixed(6)} · 估计比例 ${r.estimated_scale.toFixed(6)}\n${r.passed ? "误差检查通过" : "尚未通过：补充检查点或修正误差超限的点位"}${r.simulated ? "\n仿真数据：结果仅供仿真使用" : ""}\n连线表示各点配准后的偏差（按原图坐标显示）。`;
    $("registration-report").classList.toggle("error", !r.passed);
    this.refreshSave();
  }

  overlay(marker, polygon) {
    if (!this.active) return;
    this.points.forEach((point) => {
      const color = point.role === "check" ? "#e4a94f" : "#bc9bff";
      marker(...point.map, color, point.name);
      if (this.report) {
        const r = this.report,
          [tx, ty] = r.translation;
        const dx = (point.robot[0] - tx) / r.scale,
          dy = (point.robot[1] - ty) / r.scale;
        const c = Math.cos(r.yaw),
          s = Math.sin(r.yaw);
        const measured = [c * dx + s * dy, -s * dx + c * dy];
        polygon([point.map, measured], "#ff9eaa", false);
      }
    });
    if (this.selected) marker(...this.selected, "#f2dd87", "待采集");
  }

  close() {
    this.active = false;
    $("registration-panel").hidden = true;
    $("navigation-panel").hidden = false;
    this.host.setTool("pan");
  }
}
