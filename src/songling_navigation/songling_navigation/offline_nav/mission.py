"""Ordered, persistent task checkpoints. Position alone never advances a task."""

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import time
import uuid


def context_key(map_id, project):
    geometry = {key: project.get(key) for key in ('drivable', 'forbidden', 'clearance_m')}
    geometry['map_id'] = map_id
    return hashlib.sha256(json.dumps(geometry, sort_keys=True).encode()).hexdigest()


def pose_values(pose):
    values = {key: float(pose[key]) for key in ('x', 'y', 'yaw')}
    if not all(math.isfinite(v) for v in values.values()):
        raise ValueError('任务坐标必须是有限数值')
    return values


class MissionJournal:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.data = None
        self.sent_offset = self.sent_count = 0
        if self.path and self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                assert data['schema'] == 1 and isinstance(data['targets'], list)
                assert 1 <= len(data['targets']) <= 200
                assert type(data['next_index']) is int and 0 <= data['next_index'] <= len(data['targets'])
                for target in data['targets']:
                    pose_values(target)
                self.data = data
                if data['state'] == 'active':
                    data['state'] = 'paused'
                    data['reason'] = '服务重新启动，等待手动继续'
            except (ValueError, KeyError, TypeError, AssertionError):
                # A damaged checkpoint must not produce an inferred route.
                self.data = None

    def save(self):
        if self.path:
            temp = self.path.with_name('.mission-' + uuid.uuid4().hex)
            try:
                temp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2))
                os.replace(temp, self.path)
            finally:
                temp.unlink(missing_ok=True)

    def start(self, targets, map_id, project, confirmed=True, *, automatic=False):
        def key(pose, index):
            values = pose_values(pose)
            if automatic:
                return index, values['x'], values['y']
            return tuple(values.values())

        names = {key(w, i): w.get('name', '途径点') for i, w in enumerate(project.get('waypoints', []))}
        poses = [dict(pose_values(p), name=names.get(key(p, i), '终点' if i == len(targets)-1 else f'目标 {i+1}'))
                 for i, p in enumerate(targets)]
        self.data = dict(schema=1, task_id=uuid.uuid4().hex, context=context_key(map_id, project),
                         targets=poses, automatic_headings=automatic, next_index=0, state='active', progress_confirmed=confirmed,
                         reason='', updated_at=time.time())
        self.sent_offset, self.sent_count = 0, len(poses)
        self.save()

    def summary(self, map_id, project):
        d = self.data
        if not d:
            return dict(available=False)
        compatible = d['context'] == context_key(map_id, project)
        # Continuing uses the original terminal pose, even if the operator has
        # since selected a different terminal for a new task in the browser.
        axes = ('x', 'y') if d.get('automatic_headings') else ('x', 'y', 'yaw')
        def route_key(poses):
            return [tuple(float(pose[axis]) for axis in axes) for pose in poses]

        planned = route_key(d['targets'])
        compatible = compatible and (planned[:-1] == route_key(project.get('waypoints', []))
                                     or len(planned) == 1)
        remaining = d['targets'][d['next_index']:]
        return dict(available=bool(remaining and d['state'] != 'complete'), task_id=d['task_id'],
                    compatible=bool(compatible), state=d['state'], completed=d['next_index'],
                    total=len(d['targets']), targets=copy.deepcopy(d['targets']),
                    next_index=d['next_index'], next_name=remaining[0]['name'] if remaining else '',
                    progress_confirmed=d['progress_confirmed'], reason=d['reason'],
                    suggested_index=d.get('suggested_index', d['next_index']),
                    unavailable_reason='' if compatible else '地图或途径点已修改，请从头开始新任务')

    def prepare_resume(self, payload, map_id, project):
        s = self.summary(map_id, project)
        if not s.get('available') or payload.get('task_id') != s.get('task_id'):
            raise ValueError('上次任务已变化，请重新打开导航选项')
        if not s['compatible']:
            raise ValueError(s['unavailable_reason'])
        index = payload.get('from_index', self.data['next_index'])
        if type(index) is not int or not 0 <= index < len(self.data['targets']):
            raise ValueError('请选择有效的下一途径点')
        if not self.data['progress_confirmed'] and 'from_index' not in payload:
            raise ValueError('旧任务未记录进度，请先确认下一途径点')
        return index, [pose_values(p) for p in self.data['targets'][index:]]

    def resumed(self, index):
        self.sent_offset, self.sent_count = index, len(self.data['targets']) - index
        self.data.update(next_index=index, state='active', reason='', progress_confirmed=True)
        self.save()

    def feedback(self, remaining):
        if not self.data or self.data['state'] != 'active':
            return
        # Zero is also emitted before a BT initializes. Only SUCCEEDED completes
        # the terminal goal, and only this action's ordered count advances vias.
        if type(remaining) is not int or not 1 <= remaining <= self.sent_count:
            return
        index = self.sent_offset + self.sent_count - remaining
        if index > self.data['next_index']:
            self.data['next_index'] = index
            self.data['updated_at'] = time.time()
            self.save()

    def finish(self, success, reason):
        if self.data and self.data['state'] != 'complete':
            self.data.update(state='complete' if success else 'paused', reason=reason, updated_at=time.time())
            if success:
                self.data['next_index'] = len(self.data['targets'])
            self.save()
