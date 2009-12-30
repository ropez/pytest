import py
from py.impl.test.conftesthandle import Conftest

def pytest_generate_tests(metafunc):
    if "basedir" in metafunc.funcargnames:
        metafunc.addcall(param="global") 
        metafunc.addcall(param="inpackage")

def pytest_funcarg__basedir(request): 
    def basedirmaker(request):
        basedir = d = request.getfuncargvalue("tmpdir")
        d.ensure("adir/conftest.py").write("a=1 ; Directory = 3")
        d.ensure("adir/b/conftest.py").write("b=2 ; a = 1.5")
        if request.param == "inpackage": 
            d.ensure("adir/__init__.py")
            d.ensure("adir/b/__init__.py")
        return d 
    return request.cached_setup(lambda: basedirmaker(request), extrakey=request.param)

def ConftestWithSetinitial(path):
    conftest = Conftest()
    conftest.setinitial([path])
    return conftest

class TestConftestValueAccessGlobal:
    def test_basic_init(self, basedir):
        conftest = Conftest()
        conftest.setinitial([basedir.join("adir")])
        assert conftest.rget("a") == 1

    def test_onimport(self, basedir):
        l = []
        conftest = Conftest(onimport=l.append)
        conftest.setinitial([basedir.join("adir")])
        assert len(l) == 1 
        assert conftest.rget("a") == 1
        assert conftest.rget("b", basedir.join("adir", "b")) == 2
        assert len(l) == 2

    def test_immediate_initialiation_and_incremental_are_the_same(self, basedir):
        conftest = Conftest()
        snap0 = len(conftest._path2confmods)
        conftest.getconftestmodules(basedir)
        snap1 = len(conftest._path2confmods)
        #assert len(conftest._path2confmods) == snap1 + 1
        conftest.getconftestmodules(basedir.join('adir'))
        assert len(conftest._path2confmods) == snap1 + 1
        conftest.getconftestmodules(basedir.join('b'))
        assert len(conftest._path2confmods) == snap1 + 2

    def test_default_has_lower_prio(self, basedir):
        conftest = ConftestWithSetinitial(basedir.join("adir"))
        assert conftest.rget('Directory') == 3
        #assert conftest.lget('Directory') == py.test.collect.Directory 
        
    def test_value_access_not_existing(self, basedir):
        conftest = ConftestWithSetinitial(basedir)
        py.test.raises(KeyError, "conftest.rget('a')")
        #py.test.raises(KeyError, "conftest.lget('a')")

    def test_value_access_by_path(self, basedir):
        conftest = ConftestWithSetinitial(basedir)
        assert conftest.rget("a", basedir.join('adir')) == 1
        #assert conftest.lget("a", basedir.join('adir')) == 1
        assert conftest.rget("a", basedir.join('adir', 'b')) == 1.5 
        #assert conftest.lget("a", basedir.join('adir', 'b')) == 1
        #assert conftest.lget("b", basedir.join('adir', 'b')) == 2
        #assert py.test.raises(KeyError, 
        #    'conftest.lget("b", basedir.join("a"))'
        #)

    def test_value_access_with_init_one_conftest(self, basedir):
        conftest = ConftestWithSetinitial(basedir.join('adir'))
        assert conftest.rget("a") == 1
        #assert conftest.lget("a") == 1

    def test_value_access_with_init_two_conftests(self, basedir):
        conftest = ConftestWithSetinitial(basedir.join("adir", "b"))
        conftest.rget("a") == 1.5
        #conftest.lget("a") == 1
        #conftest.lget("b") == 1

    def test_value_access_with_confmod(self, basedir):
        topdir = basedir.join("adir", "b")
        topdir.ensure("xx", dir=True)
        conftest = ConftestWithSetinitial(topdir)
        mod, value = conftest.rget_with_confmod("a", topdir)
        assert  value == 1.5
        path = py.path.local(mod.__file__)
        assert path.dirpath() == basedir.join("adir", "b")
        assert path.purebasename == "conftest"
