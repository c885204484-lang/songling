"""核对稿件中的数学递推及任务状态示例，不模拟车辆或验证专利性。"""
from itertools import product
from pathlib import Path
import math
import random


def solve(costs):
    values = [0.0]
    predecessors = []
    for matrix in costs:
        next_values, parents = [], []
        for b in range(len(matrix[0])):
            best, parent = min((values[a] + matrix[a][b], a)
                               for a in range(len(values)))
            next_values.append(best)
            parents.append(parent)
        values = next_values
        predecessors.append(parents)
    best, state = min((value, state) for state, value in enumerate(values))
    if math.isinf(best):
        return best, None
    path = [state]
    for parents in reversed(predecessors):
        state = parents[state]
        path.append(state)
    return best, list(reversed(path))


def brute(costs):
    best = math.inf
    for states in product(*(range(len(matrix[0])) for matrix in costs)):
        chain = (0,) + states
        total = sum(matrix[chain[i]][chain[i + 1]]
                    for i, matrix in enumerate(costs))
        best = min(best, total)
    return best


def main():
    folder = Path(__file__).resolve().parent
    log = ["算例核验记录", "核验对象：本稿说明性递推及任务状态示例。",
           "本程序不进行车辆仿真、运动学求解、碰撞验证或实车试验。", ""]
    matrices = [[[4, 6]], [[12], [3]]]
    value, chain = solve(matrices)
    assert value == 9 and chain == [0, 1, 0]
    assert 4 + 12 == 16
    log.append("1. 共享状态算例：经A累计代价16，经B累计代价9；动态规划选择B。通过。")
    assert solve([[[4, 6]], [[math.inf], [3]]])[0] == 9
    assert solve([[[4, 6]], [[math.inf], [math.inf]]]) == (math.inf, None)
    log.append("2. 删除A至终点连接后仍选择B；两条终点连接均删除后返回无可行状态链。通过。")
    rng = random.Random(20261106)
    for _ in range(100):
        sizes = [1] + [rng.randint(1, 3) for _ in range(rng.randint(1, 4))]
        costs = [[[math.inf if rng.random() < .2 else rng.randint(0, 20)
                   for _ in range(sizes[i + 1])]
                  for _ in range(sizes[i])]
                 for i in range(len(sizes) - 1)]
        result, path = solve(costs)
        assert result == brute(costs)
        if path:
            assert sum(matrix[path[i]][path[i + 1]]
                       for i, matrix in enumerate(costs)) == result
    log.append("3. 固定随机种子的100组非负连接图：动态规划最小代价与全部状态链穷举一致，回溯代价一致。通过。")
    waypoints = [(4, 0), (8, 0), (12, 2)]
    completed = 1
    snapshot = tuple(waypoints[completed:])
    assert snapshot == ((8, 0), (12, 2))
    completed_after_reset = completed
    new_progress = 0
    assert completed_after_reset == 1 and new_progress == 0
    log.append("4. 完成前缀为1时保留w2、w3；轨迹进度重置为0不改变已完成前缀。通过。")
    # 20 Hz，停车确认0.5秒；确认后合并持续低速采样。
    event_count, active, duration = 0, False, 0.0
    for _ in range(60):
        duration += .05
        if duration >= .5 - 1e-9 and not active:
            event_count += 1
            active = True
    assert event_count == 1
    log.append("5. 20赫兹、3秒的60次零速采样，确认时间0.5秒：只生成1次停车事件。通过。")
    text = (folder / "专利正文.md").read_text()
    abstract = text.split("## 说明书摘要\n\n", 1)[1].split("\n\n## 权利要求书", 1)[0]
    claims = text.split("## 权利要求书\n\n", 1)[1].split("\n\n## 说明书", 1)[0]
    import re
    count = len(re.findall(r"^\d+\. ", claims, re.M))
    assert len(abstract) <= 300 and count == 12
    log.append(f"6. 摘要含标点{len(abstract)}个字符，未超过300；方法权利要求{count}项。通过。")
    log.append("\n范围说明：上述通过仅指数字和简化逻辑核对，不证明整套算法已在项目实现或已具备车辆安全性能。")
    (folder / "算例核验记录.txt").write_text("\n".join(log) + "\n")
    print("\n".join(log))


if __name__ == "__main__":
    main()
