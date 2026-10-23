"""Check coordinate conventions and automatic projection's save boundary."""

import copy
from types import SimpleNamespace

import numpy as np
import pytest

from songling_navigation.amap_keepout import AmapStaticImage
from songling_navigation.offline_nav.maps import MapModel
from songling_navigation.offline_nav.geodetic import geographic_samples, projection_report, projected_document
from songling_navigation.offline_nav.server import Application


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
    aligned, transformed = projected_document(model, p, report, 'original')
    assert aligned.display_image is not None
    assert transformed['forbidden'][0][0] == pytest.approx([110, 130])
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
