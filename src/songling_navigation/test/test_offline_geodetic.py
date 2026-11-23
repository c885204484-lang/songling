"""Check coordinate conventions and automatic projection's save boundary."""

import copy
from types import SimpleNamespace

import numpy as np
import pytest

from songling_navigation.amap_keepout import AmapStaticImage
from songling_navigation.offline_nav.maps import MapModel
from songling_navigation.offline_nav.geodetic import geographic_samples, projection_report, projected_document
from songling_navigation.offline_nav.server import Application
from songling_navigation.offline_nav.registration import fit_registration, registered_document, landmark_translation


def test_landmark_translation_previews_offset_without_verifying_accuracy():
    model = MapModel.demo()
    project = model.empty_project()
    project['navigation_goal'] = dict(x=2., y=3., yaw=.2)
    report = landmark_translation(model, dict(points=[dict(map=[0., 0.],robot=[3., 4.])]))
    assert report['translation'] == [3., 4.]
    assert report['passed'] is False
    assert report['accuracy_verified'] is False
    aligned, candidate = registered_document(model, project, report, 'source')
    assert aligned.origin[:2] == pytest.approx([model.origin[0]+3.,model.origin[1]+4.])
    assert candidate['navigation_goal']['x'] == pytest.approx(5.)
    assert candidate['navigation_goal']['y'] == pytest.approx(7.)
    assert aligned.context['georeference']['registration']['accuracy_verified'] is False


def test_landmark_translation_can_save_preview_but_not_mark_it_field_verified(tmp_path):
    app = Application(tmp_path, demo=True, sample=True)
    app.update(app.project)
    original = app.revision
    payload = dict(method='landmark_translation',revision=original,
                   project=copy.deepcopy(app.project),fixed_frame_confirmed=True,
                   points=[dict(map=[0.,0.],robot=[3.,4.])])
    result = app.register(payload,commit=True)
    assert result['revision'] != original
    assert (tmp_path / original / 'project.json').exists()
    r = result['project']['map']['georeference']['registration']
    assert r['method'] == 'landmark_translation'
    assert r['passed'] is False
    assert r['accuracy_verified'] is False


@pytest.mark.parametrize('points', [[],[dict(map=[0.,0.],robot=[float('nan'),0.])],
                                   [dict(map=[10000.,10000.],robot=[0.,0.])]])
def test_landmark_translation_rejects_invalid_points(points):
    with pytest.raises(ValueError):
        landmark_translation(MapModel.demo(),dict(points=points))


def test_field_registration_requires_independent_check_and_moves_terminal_pose():
    model = MapModel.demo()
    project = model.empty_project()
    project['navigation_goal'] = dict(x=2., y=3., yaw=.2)
    locations = [[0., 0.], [10., 0.], [0., 10.], [10., 10.]]
    points = [dict(map=p, robot=[p[0]+4.,p[1]+5.],role='check' if i==3 else 'fit')
              for i,p in enumerate(locations)]
    report = fit_registration(model, dict(points=points))
    aligned, saved = registered_document(model, project, report, 'source')
    assert aligned.context['georeference']['registration']['accuracy_verified'] is True
    assert saved['navigation_goal']['x'] == pytest.approx(6.)
    assert saved['navigation_goal']['y'] == pytest.approx(8.)
    assert saved['navigation_goal']['yaw'] == pytest.approx(.2)
    report['simulated'] = True
    simulated, _ = registered_document(model, project, report, 'source')
    assert simulated.context['georeference']['registration']['accuracy_verified'] is False


def test_geographic_samples_roundtrip_pixels_without_y_flip_or_gcj_offset():
    model = MapModel.default_site()
    geo = model.context['georeference']
    image = AmapStaticImage(np.asarray(model.display_image), geo['center_gcj02'][1],
                           geo['center_gcj02'][0], geo['zoom'], model.width, geo['scale'])
    for sample in geographic_samples(model):
        px, py = image.wgs84_to_pixel(sample['lon'], sample['lat'])
        gx, gy = model.world_to_grid(*sample['map'])
        assert [float(px), float(py)] == pytest.approx([gx, model.height-gy], abs=1e-5)


def test_projection_transforms_regions_and_preserves_image_and_accuracy_label():
    model = MapModel.default_site()
    samples = geographic_samples(model)
    targets = [[p['map'][0] + 120, p['map'][1] + 140] for p in samples]
    report = projection_report(model, samples, targets)
    p = model.empty_project()
    p['forbidden'] = [[[-10, -10], [10, -10], [10, 10], [-10, 10]]]
    p['navigation_goal'] = dict(x=2., y=3., yaw=.2)
    aligned, transformed = projected_document(model, p, report, 'original')
    assert aligned.display_image is not None
    assert transformed['forbidden'][0][0] == pytest.approx([110, 130])
    assert transformed['navigation_goal']['x'] == pytest.approx(122.)
    assert transformed['navigation_goal']['y'] == pytest.approx(143.)
    assert aligned.context['georeference']['registration']['accuracy_verified'] is False
    assert aligned.context['georeference']['registration']['method'] == 'geodetic_fromll'
    assert model.context['georeference']['navigation_aligned'] is False
    with pytest.raises(ValueError, match='原快照'):
        geographic_samples(aligned)


def test_projection_rejects_nonuniform_distortion_and_uninitialized_service():
    model = MapModel.default_site()
    samples = geographic_samples(model)
    distorted = [[p['map'][0], p['map'][1]] for p in samples]
    distorted[1][0] += 10
    for targets in ([[0, 0]] * len(samples), distorted):
        with pytest.raises(ValueError):
            projection_report(model, samples, targets)


def test_affine_projection_handles_ellipsoid_scale_and_preserves_keepouts():
    model = MapModel.default_site()
    samples = geographic_samples(model)
    targets = [[p['map'][0]*1.0002 + p['map'][1]*-.00008 + 126.53,
                p['map'][0]*-.00173 + p['map'][1]*.99619 + 141.63] for p in samples]
    report = projection_report(model, samples, targets)
    assert report['check_max_m'] < 1e-8
    p = model.empty_project()
    p['drivable'] = [[model.grid_to_world(x,y) for x,y in ((50,50),(1550,50),(1550,1550),(50,1550))]]
    p['forbidden'] = [[[-10,-10],[10,-10],[10,10],[-10,10]]]
    aligned, transformed = projected_document(model, p, report, 'original')
    grid = aligned.rasterize(transformed)
    assert aligned.origin[2] == 0
    assert not aligned.is_free(grid,126.53,141.63)
    assert aligned.is_free(grid,226.55,141.457)


def test_auto_save_uses_live_service_and_preserves_previous_snapshot(tmp_path):
    app = Application(tmp_path)
    app.update(app.project)
    previous = app.revision
    def convert(samples):
        return [[p['map'][0] + 120, p['map'][1] + 140] for p in samples]
    app.bridge = SimpleNamespace(status=lambda: dict(busy=False, connection={}),
                                 project_geographic=convert)
    payload = dict(method='geodetic_fromll', revision=previous, project=copy.deepcopy(app.project))
    state = app.register(payload, commit=True)
    assert state['revision'] != previous
    assert (tmp_path / previous / 'original.yaml').exists()
    assert state['project']['map']['georeference']['navigation_aligned'] is True
    with pytest.raises(ValueError, match='快照已变化'):
        app.register(payload, commit=True)
