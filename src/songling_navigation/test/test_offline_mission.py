"""Resume ordered routes, including crossings, without guessing from position."""
import copy
from types import SimpleNamespace
import threading

import pytest
from songling_navigation.offline_nav.mission import MissionJournal


def project():
    # Repeated crossing coordinates deliberately cannot identify task progress.
    poses=[dict(x=0,y=0,yaw=0,name='航点 1'),dict(x=3,y=2,yaw=1,name='航点 2'),
           dict(x=0,y=0,yaw=2,name='航点 3'),dict(x=3,y=-2,yaw=0,name='航点 4')]
    return dict(drivable=[],forbidden=[],clearance_m=.65,waypoints=poses,
                navigation_goal=dict(x=7,y=0,yaw=1.2))


def task(journal=None):
    journal=journal or MissionJournal()
    p=project();journal.start(p['waypoints']+[p['navigation_goal']], 'map-a', p)
    return journal,p


def test_figure_eight_progress_comes_from_ordered_feedback_not_nearest_position():
    j,p=task();j.feedback(2);j.finish(False,'碰撞暂停')
    summary=j.summary('map-a',p)
    assert summary['completed']==3 and summary['next_name']=='航点 4'
    index,poses=j.prepare_resume({'task_id':summary['task_id']},'map-a',p)
    assert index==3 and poses==[{k:p['waypoints'][3][k] for k in ('x','y','yaw')},p['navigation_goal']]


def test_resumed_feedback_keeps_original_offset():
    j,p=task();j.feedback(2);j.resumed(3);j.feedback(1)
    assert j.data['next_index']==4
    assert len(j.prepare_resume({'task_id':j.data['task_id']},'map-a',p)[1])==1


@pytest.mark.parametrize('remaining',[0,-1,6,True,2.0])
def test_invalid_feedback_never_skips_goals(remaining):
    j,p=task();j.feedback(remaining);assert j.data['next_index']==0


def test_out_of_order_counts_never_rewind_and_only_success_completes():
    j,p=task();j.feedback(1);j.feedback(5);j.feedback(0)
    assert j.data['next_index']==4 and j.summary('map-a',p)['available']
    j.finish(True,'到达');assert not j.summary('map-a',p)['available']


def test_checkpoint_survives_restart_and_never_auto_starts(tmp_path):
    j,p=task(MissionJournal(tmp_path/'mission.json'));j.feedback(2)
    loaded=MissionJournal(tmp_path/'mission.json')
    assert loaded.data['state']=='paused' and loaded.data['next_index']==3


@pytest.mark.parametrize('change',['map','keepout','waypoint'])
def test_changed_map_or_route_blocks_resume(change):
    j,p=task();map_id='map-a'
    if change=='map':map_id='different'
    elif change=='keepout':p['forbidden']=[[[0,0],[1,0],[0,1]]]
    else:p['waypoints'][0]['yaw']=2
    with pytest.raises(ValueError,match='修改'):
        j.prepare_resume({'task_id':j.data['task_id']},map_id,p)


def test_original_terminal_is_preserved_if_browser_selects_new_goal():
    j,p=task();original=copy.deepcopy(p['navigation_goal']);p['navigation_goal']['yaw']=2.5
    _,poses=j.prepare_resume({'task_id':j.data['task_id']},'map-a',p)
    assert poses[-1]==original


def test_automatic_route_resumes_with_resolved_headings_and_ordered_names(tmp_path):
    p = project()
    targets = [dict(wp, yaw=.5) for wp in p['waypoints'] + [p['navigation_goal']]]
    journal = MissionJournal(tmp_path / 'mission.json')
    journal.start(targets, 'map-a', p, automatic=True)
    loaded = MissionJournal(journal.path)
    summary = loaded.summary('map-a', p)
    assert summary['compatible']
    assert [target['name'] for target in summary['targets']] == [
        '航点 1', '航点 2', '航点 3', '航点 4', '终点',
    ]
    _, resumed = loaded.prepare_resume({'task_id': summary['task_id']}, 'map-a', p)
    assert [target['yaw'] for target in resumed] == [.5] * 5
    p['waypoints'][0]['x'] += 1
    assert not loaded.summary('map-a', p)['compatible']


def test_legacy_progress_requires_explicit_next_target_confirmation():
    j,p=task();j.data['progress_confirmed']=False
    with pytest.raises(ValueError,match='确认'):
        j.prepare_resume({'task_id':j.data['task_id']},'map-a',p)
    i,poses=j.prepare_resume({'task_id':j.data['task_id'],'from_index':3},'map-a',p)
    assert i==3 and len(poses)==2


def test_stale_task_id_cannot_resume_new_mission():
    j,p=task();old=j.data['task_id'];task(j)
    with pytest.raises(ValueError,match='变化'):
        j.prepare_resume({'task_id':old},'map-a',p)


def test_old_action_feedback_cannot_advance_replacement_task():
    pytest.importorskip('rclpy')
    from songling_navigation.offline_nav.ros_bridge import NavigationBridge
    j,p=task();b=SimpleNamespace(operation=2,mission=j,state_lock=threading.RLock())
    NavigationBridge.on_route_feedback(b,SimpleNamespace(feedback=SimpleNamespace(number_of_poses_remaining=1)),1)
    assert j.data['next_index']==0


def test_corrupt_checkpoint_is_not_resumed(tmp_path):
    p=tmp_path/'mission.json';p.write_text('{broken')
    assert MissionJournal(p).data is None


def test_resuming_a_paused_task_does_not_advance_from_stationary_feedback():
    j,p=task();j.feedback(2);j.finish(False,'cancelled')
    j.feedback(1)
    assert j.data['next_index']==3


def test_resume_rejects_boolean_or_out_of_range_target_index():
    j,p=task()
    for index in [True,-1,5,'3']:
        with pytest.raises(ValueError,match='有效'):
            j.prepare_resume({'task_id':j.data['task_id'],'from_index':index},'map-a',p)
