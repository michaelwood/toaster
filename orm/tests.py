from django.test import TestCase, TransactionTestCase
from orm.models import LocalLayerSource, LayerIndexLayerSource, ImportedLayerSource, LayerSource
from orm.models import Branch

from orm.models import Project, Build, Layer, Layer_Version, Branch, ProjectLayer
from orm.models import Release, ReleaseLayerSourcePriority, BitbakeVersion

from django.utils import timezone
from django.db import IntegrityError

import os

# set TTS_LAYER_INDEX to the base url to use a different instance of the layer index

class LayerSourceVerifyInheritanceSaveLoad(TestCase):
    """
    Tests to verify inheritance for the LayerSource proxy-inheritance classes.
    """
    def test_object_creation(self):
        """Test LayerSource object creation."""
        for name, sourcetype in [("a1", LayerSource.TYPE_LOCAL),
                                 ("a2", LayerSource.TYPE_LAYERINDEX),
                                 ("a3", LayerSource.TYPE_IMPORTED)]:
            LayerSource.objects.create(name=name, sourcetype=sourcetype)

        objects = LayerSource.objects.all()
        self.assertTrue(isinstance(objects[0], LocalLayerSource))
        self.assertTrue(isinstance(objects[1], LayerIndexLayerSource))
        self.assertTrue(isinstance(objects[2], ImportedLayerSource))

    def test_duplicate_error(self):
        """Test creation of duplicate LayerSource objects."""
        stype = LayerSource.TYPE_LOCAL
        LayerSource.objects.create(name="a1", sourcetype=stype)
        with self.assertRaises(IntegrityError):
            LayerSource.objects.create(name="a1", sourcetype=stype)


class LILSUpdateTestCase(TransactionTestCase):
    """Test Layer Source update."""

    def setUp(self):
        """Create release."""
        bbv = BitbakeVersion.objects.create(\
                  name="master", giturl="git://git.openembedded.org/bitbake")
        Release.objects.create(name="default-release", bitbake_version=bbv,
                               branch_name="master")

    def test_update(self):
        """Check if LayerSource.update can fetch branches."""
        url = os.getenv("TTS_LAYER_INDEX",
                        default="http://layers.openembedded.org/")

        lsobj = LayerSource.objects.create(\
                    name="b1", sourcetype=LayerSource.TYPE_LAYERINDEX,
                    apiurl=url + "layerindex/api/")
        lsobj.update()
        self.assertTrue(lsobj.branch_set.all().count() > 0,
                        "no branches fetched")


def setup_lv_tests(self):
    """Create required objects."""
    # create layer source
    self.lsrc = LayerSource.objects.create(name="dummy-layersource",
                                           sourcetype=LayerSource.TYPE_LOCAL)
    # create release
    bbv = BitbakeVersion.objects.create(\
              name="master", giturl="git://git.openembedded.org/bitbake")
    self.release = Release.objects.create(name="default-release",
                                          bitbake_version=bbv,
                                          branch_name="master")
    # attach layer source to release
    ReleaseLayerSourcePriority.objects.create(\
        release=self.release, layer_source=self.lsrc, priority=1)

    # create a layer version for the layer on the specified branch
    self.layer = Layer.objects.create(name="meta-testlayer",
                                      layer_source=self.lsrc)
    self.branch = Branch.objects.create(name="master", layer_source=self.lsrc)
    self.lver = Layer_Version.objects.create(\
        layer=self.layer, layer_source=self.lsrc, up_branch=self.branch)

    # create project and project layer
    self.project = Project.objects.create_project(name="test-project",
                                                  release=self.release)
    ProjectLayer.objects.create(project=self.project,
                                layercommit=self.lver)

class LayerVersionEquivalenceTestCase(TestCase):
    """Verify Layer_Version priority selection."""

    def setUp(self):
        setup_lv_tests(self)
        # create spoof layer that should not appear in the search results
        layer = Layer.objects.create(name="meta-notvalid",
                                     layer_source=self.lsrc)
        Layer_Version.objects.create(layer=layer, layer_source=self.lsrc,
                                     up_branch=self.branch)

    def test_single_layersource(self):
        """
        When we have a single layer version,
        get_equivalents_wpriority() should return a list with
        just this layer_version.
        """
        equivqs = self.lver.get_equivalents_wpriority(self.project)
        self.assertEqual(list(equivqs), [self.lver])

    def test_dual_layersource(self):
        """
        If we have two layers with the same name, from different layer sources,
        we expect both layers in, in increasing priority of the layer source.
        """
        lsrc2 = LayerSource.objects.create(\
                    name="dummy-layersource2",
                    sourcetype=LayerSource.TYPE_LOCAL,
                    apiurl="test")

        # assign a lower priority for the second layer source
        self.release.releaselayersourcepriority_set.create(layer_source=lsrc2,
                                                           priority=2)

        # create a new layer_version for a layer with the same name
        # coming from the second layer source
        layer2 = Layer.objects.create(name="meta-testlayer",
                                      layer_source=lsrc2)
        lver2 = Layer_Version.objects.create(layer=layer2, layer_source=lsrc2,
                                             up_branch=self.branch)

        # expect two layer versions, in the priority order
        equivqs = self.lver.get_equivalents_wpriority(self.project)
        self.assertEqual(list(equivqs), [lver2, self.lver])

    def test_build_layerversion(self):
        """
        Any layer version coming from the build should show up
        before any layer version coming from upstream
        """
        build = Build.objects.create(project=self.project,
                                     started_on=timezone.now(),
                                     completed_on=timezone.now())
        lvb = Layer_Version.objects.create(layer=self.layer, build=build,
                                           commit="deadbeef")

        # a build layerversion must be in the equivalence
        # list for the original layerversion
        equivqs = self.lver.get_equivalents_wpriority(self.project)
        self.assertTrue(len(equivqs) == 2)
        self.assertTrue(equivqs[0] == self.lver)
        self.assertTrue(equivqs[1] == lvb)

        # getting the build layerversion equivalent list must
        # return the same list as the original layer
        bequivqs = lvb.get_equivalents_wpriority(self.project)

        self.assertEqual(list(equivqs), list(bequivqs))

class ProjectLVSelectionTestCase(TestCase):

    def setUp(self):
        setup_lv_tests(self)

    def test_single_layersource(self):
        compat_lv = self.project.compatible_layerversions()
        self.assertEqual(list(compat_lv), [self.lver])

